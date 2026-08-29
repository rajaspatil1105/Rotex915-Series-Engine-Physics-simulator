"""
Stage 4 health parameter layer for the Rotax 915 iSc A simulator.

Architecture:
- input: Stage 1.3/2 EngineState from get_engine_state()
- output: health telemetry with explicit provenance
- production authority remains the calibrated Rotax CSV/interpolator
- Cantera remains out of the production path

This module uses documented Rotax limits, the official generator current graph
digitization from Figure 3.5 at 135 C oil temperature, and transparent Tier-2
proxy formulas where no authoritative dynamic relationship was found.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Literal

try:
    from stage1_3_hybrid_engine_output import EngineState
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage1_3_hybrid_engine_output import EngineState


CSV_AUTHORITATIVE = "calibrated_csv"
PROVENANCE_LABELS = {
    "csv_authoritative",
    "official_limit",
    "official_specification",
    "official_architecture",
    "official_procedure",
    "official_graph_digitized",
    "tier2_proxy",
    "tier2_assumption",
    "unknown",
}

MAX_COOLANT_TEMP_C = 120.0
MAX_EGT_C = 950.0
EGT_SPREAD_LIMIT_HIGH_LPH_C = 200.0
EGT_SPREAD_LIMIT_LOW_LPH_C = 500.0
FUEL_DENSITY_PROXY_KG_PER_L = 0.75
OIL_PRESSURE_LOW_RPM_MIN_BAR = 0.8
OIL_PRESSURE_LOW_RPM_MAX_BAR = 5.0
OIL_PRESSURE_HIGH_RPM_MIN_BAR = 2.0
OIL_PRESSURE_HIGH_RPM_MAX_BAR = 5.0
OIL_PRESSURE_COLD_START_MAX_BAR = 7.0
OIL_PRESSURE_STARTUP_REQUIRED_BAR = 3.0
OIL_PRESSURE_STARTUP_RISE_TIME_S = 10.0
OIL_TEMPERATURE_MIN_START_C = -20.0
OIL_TEMPERATURE_MIN_TAKEOFF_C = 50.0
OIL_TEMPERATURE_MAX_C = 130.0
BATTERY_VOLTAGE_MIN_V = 9.0
BATTERY_VOLTAGE_MAX_V = 14.5
GENERATOR_VOLTAGE_MIN_V = 13.9
GENERATOR_VOLTAGE_MAX_V = 14.5
GENERATOR_AIRFRAME_MAX_POWER_W = 420.0
GENERATOR_EMS_CONTINUOUS_POWER_W = 230.0
GENERATOR_EMS_PEAK_POWER_W = 290.0
GENERATOR_SWITCH_THRESHOLD_RPM = 2400.0
GENERATOR_SWITCH_HOLD_TIME_S = 8.0
GENERATOR_GRAPH_CONDITION_C = 135.0

GENERATOR_A_CURVE = {
    2000.0: 3.0,
    2500.0: 9.0,
    3000.0: 16.0,
    4000.0: 28.0,
    5000.0: 38.0,
    5500.0: 42.0,
    5800.0: 44.0,
}

GENERATOR_B_CURVE = {
    2000.0: 0.0,
    2500.0: 3.0,
    3000.0: 11.0,
    4000.0: 25.0,
    5000.0: 36.0,
    5500.0: 40.0,
    5800.0: 42.0,
}


@dataclass(frozen=True)
class ProvenanceEntry:
    label: str
    reference: str
    note: str = ""


@dataclass(frozen=True)
class GeneratorSwitchState:
    ready: bool
    latched: bool
    threshold_rpm: float
    hold_time_s: float
    provenance: ProvenanceEntry


@dataclass(frozen=True)
class HealthState:
    rpm: float
    throttle_pct: float
    altitude_ft: float
    ambient_temp_C: float
    power_kW: float
    torque_Nm: float
    fuelflow_kgh: float
    p_plenum_bar: float
    t_plenum_K: float
    coolant_temp_C: float
    EGT1_C: float
    EGT2_C: float
    EGT3_C: float
    EGT4_C: float
    EGT_mean_C: float
    EGT_max_C: float
    EGT_min_C: float
    EGT_spread_C: float
    oil_pressure_bar: float
    oil_temperature_C: float
    battery_voltage_V: float
    battery_soc_pct: float
    generator_A_current_A: float
    generator_B_current_A: float
    generator_voltage_V: float
    generator_power_W: float
    generator_switch_ready: bool
    generator_switch_latched: bool
    generator_switch_threshold_rpm: float
    generator_switch_hold_time_s: float
    vibration_amplitude: float
    vibration_frequency_Hz: float
    vibration_1x: float
    vibration_2x: float
    vibration_3x: float
    production_source: str
    stage4_source_types: tuple[str, ...]
    provenance: dict[str, ProvenanceEntry]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _sorted_curve_items(curve: dict[float, float]) -> list[tuple[float, float]]:
    return sorted((float(rpm), float(value)) for rpm, value in curve.items())


def _linear_interp(rpm: float, curve: dict[float, float]) -> float:
    rpm = float(rpm)
    points = _sorted_curve_items(curve)
    if rpm <= points[0][0]:
        return points[0][1]
    if rpm >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        if x0 <= rpm <= x1:
            if x1 == x0:
                return y0
            frac = (rpm - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return points[-1][1]


def lookup_digitized_generator_current(rpm: float, generator: Literal["A", "B"]) -> float:
    """Linearly interpolate the digitized Figure 3.5 generator-current points."""

    curve = GENERATOR_A_CURVE if generator == "A" else GENERATOR_B_CURVE
    return _linear_interp(rpm, curve)


def egt_spread_limit_from_fuel_flow(fuelflow_kgh: float) -> float:
    """Return the documented EGT spread limit using a simple fuel-flow proxy."""

    fuel_flow_lph_proxy = float(fuelflow_kgh) / FUEL_DENSITY_PROXY_KG_PER_L
    return EGT_SPREAD_LIMIT_HIGH_LPH_C if fuel_flow_lph_proxy > 3.0 else EGT_SPREAD_LIMIT_LOW_LPH_C


def update_generator_switch_timer(
    previous_time_above_threshold_s: float,
    rpm: float,
    dt_s: float,
) -> float:
    """Advance the continuous above-threshold timer with an explicit timestep.

    The timer increments only while RPM remains at or above the switching
    threshold. Any drop below the threshold resets the timer to zero.
    """

    previous_time_above_threshold_s = max(0.0, float(previous_time_above_threshold_s))
    dt_s = float(dt_s)
    if dt_s < 0.0:
        raise ValueError("dt_s must be non-negative")
    if float(rpm) >= GENERATOR_SWITCH_THRESHOLD_RPM:
        return previous_time_above_threshold_s + dt_s
    return 0.0


def generator_switch_state(
    rpm: float,
    time_above_threshold_s: float | None = None,
) -> GeneratorSwitchState:
    """Simple switch logic for the documented >2400 RPM / 8 s generator behavior.

    The latch decision is based on continuous time at or above the threshold,
    not on total mission runtime. Callers should explicitly track and pass the
    accumulated above-threshold time between timesteps.
    """

    ready = float(rpm) >= GENERATOR_SWITCH_THRESHOLD_RPM
    latched = bool(
        ready
        and time_above_threshold_s is not None
        and float(time_above_threshold_s) >= GENERATOR_SWITCH_HOLD_TIME_S
    )
    provenance = ProvenanceEntry(
        label="official_procedure",
        reference="Rotax IM-915 i A generator switching procedure",
        note="Threshold around 2400 RPM with 8 second hold time.",
    )
    return GeneratorSwitchState(
        ready=ready,
        latched=latched,
        threshold_rpm=GENERATOR_SWITCH_THRESHOLD_RPM,
        hold_time_s=GENERATOR_SWITCH_HOLD_TIME_S,
        provenance=provenance,
    )


def _entry(label: str, reference: str, note: str = "") -> ProvenanceEntry:
    if label not in PROVENANCE_LABELS:
        raise ValueError(f"Unsupported provenance label: {label}")
    return ProvenanceEntry(label=label, reference=reference, note=note)


def _validate_engine_state(engine_state: EngineState) -> None:
    for name in [
        "rpm",
        "throttle_pct",
        "altitude_ft",
        "ambient_temp_C",
        "power_kW",
        "torque_Nm",
        "fuelflow_kgh",
        "p_plenum_bar",
        "t_plenum_K",
    ]:
        value = getattr(engine_state, name)
        if value is None or not isfinite(float(value)):
            raise ValueError(f"engine_state.{name} must be finite")


def get_health_state(
    engine_state: EngineState,
    runtime_s: float | None = None,
    *,
    time_above_threshold_s: float | None = None,
) -> HealthState:
    """Build a Stage 4 health state from the authoritative engine state.

    ``time_above_threshold_s`` is the preferred input for generator latch
    logic. ``runtime_s`` is retained as a compatibility alias for existing
    callers that have not yet been updated.
    """

    _validate_engine_state(engine_state)

    rpm = float(engine_state.rpm)
    throttle_pct = float(engine_state.throttle_pct)
    altitude_ft = float(engine_state.altitude_ft)
    ambient_temp_C = float(engine_state.ambient_temp_C)
    power_kW = float(engine_state.power_kW)
    torque_Nm = float(engine_state.torque_Nm)
    fuelflow_kgh = float(engine_state.fuelflow_kgh)
    p_plenum_bar = float(engine_state.p_plenum_bar)
    t_plenum_K = float(engine_state.t_plenum_K)
    mat_C = t_plenum_K - 273.15

    load_ratio = _clamp(power_kW / 105.0, 0.0, 1.2)
    pressure_ratio = _clamp(p_plenum_bar / 1.55, 0.0, 1.25)
    ambient_positive = max(0.0, ambient_temp_C)

    coolant_temp_C = _clamp(
        55.0 + 22.0 * load_ratio + 8.0 * pressure_ratio + 0.06 * ambient_positive + 0.00025 * altitude_ft,
        OIL_TEMPERATURE_MIN_START_C,
        MAX_COOLANT_TEMP_C,
    )

    spread_limit = egt_spread_limit_from_fuel_flow(fuelflow_kgh)
    egt_mean_C = _clamp(
        330.0 + 260.0 * load_ratio + 0.45 * mat_C + 0.02 * (rpm - 3000.0) + 4.0 * pressure_ratio,
        200.0,
        MAX_EGT_C,
    )
    egt_spread_C = _clamp(
        70.0 + 55.0 * load_ratio + 12.0 * pressure_ratio + 0.03 * max(0.0, rpm - 3000.0) / 100.0,
        20.0,
        spread_limit,
    )
    egt_offsets = (-0.5, -1.0 / 6.0, 1.0 / 6.0, 0.5)
    egt_values = [
        _clamp(egt_mean_C + offset * egt_spread_C, 0.0, MAX_EGT_C) for offset in egt_offsets
    ]
    egt_min_C = min(egt_values)
    egt_max_C = max(egt_values)
    egt_spread_C = egt_max_C - egt_min_C

    oil_temperature_C = _clamp(
        64.0 + 0.15 * power_kW + 0.00035 * altitude_ft + 0.02 * ambient_positive,
        OIL_TEMPERATURE_MIN_START_C,
        OIL_TEMPERATURE_MAX_C,
    )
    temp_penalty = max(0.0, oil_temperature_C - 100.0) / 40.0
    load_bonus = 0.6 * load_ratio + 0.4 * pressure_ratio
    if rpm < 3500.0:
        oil_pressure_bar = _clamp(
            0.8 + 0.00045 * rpm + 1.0 * load_bonus - 0.6 * temp_penalty,
            OIL_PRESSURE_LOW_RPM_MIN_BAR,
            OIL_PRESSURE_LOW_RPM_MAX_BAR,
        )
    else:
        oil_pressure_bar = _clamp(
            2.0 + 0.00055 * (rpm - 3500.0) + 1.0 * load_bonus - 0.6 * temp_penalty,
            OIL_PRESSURE_HIGH_RPM_MIN_BAR,
            OIL_PRESSURE_HIGH_RPM_MAX_BAR,
        )

    switch_time_s = time_above_threshold_s if time_above_threshold_s is not None else runtime_s
    gen_switch = generator_switch_state(rpm, time_above_threshold_s=switch_time_s)
    generator_A_current_A = lookup_digitized_generator_current(rpm, "A")
    generator_B_current_A = lookup_digitized_generator_current(rpm, "B")
    if gen_switch.ready:
        generator_voltage_V = _clamp(
            GENERATOR_VOLTAGE_MIN_V
            + (GENERATOR_VOLTAGE_MAX_V - GENERATOR_VOLTAGE_MIN_V)
            * (rpm - GENERATOR_SWITCH_THRESHOLD_RPM)
            / (5800.0 - GENERATOR_SWITCH_THRESHOLD_RPM),
            GENERATOR_VOLTAGE_MIN_V,
            GENERATOR_VOLTAGE_MAX_V,
        )
        generator_power_W = min(
            generator_voltage_V * generator_B_current_A,
            GENERATOR_AIRFRAME_MAX_POWER_W,
        )
    else:
        generator_voltage_V = _clamp(12.4 + 0.0004 * rpm, 9.0, GENERATOR_VOLTAGE_MIN_V)
        generator_power_W = 0.0

    battery_voltage_V = _clamp(
        12.1 + 2.4 * (generator_power_W / GENERATOR_AIRFRAME_MAX_POWER_W),
        BATTERY_VOLTAGE_MIN_V,
        BATTERY_VOLTAGE_MAX_V,
    )
    battery_soc_pct = _clamp(55.0 + 15.0 * (battery_voltage_V - 12.1), 0.0, 100.0)

    vibration_amplitude = 0.08 + 0.000045 * rpm + 0.02 * load_ratio
    vibration_frequency_Hz = rpm / 60.0
    vibration_1x = vibration_amplitude
    vibration_2x = vibration_amplitude * 0.6
    vibration_3x = vibration_amplitude * 0.4

    provenance = {
        "rpm": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "throttle_pct": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "altitude_ft": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "ambient_temp_C": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "power_kW": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "torque_Nm": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "fuelflow_kgh": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "p_plenum_bar": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "t_plenum_K": _entry("csv_authoritative", "Rotax performance-map CSV"),
        "coolant_temp_C": _entry(
            "tier2_proxy",
            "Rotax 915 i A Operator Manual and Installation Manual limits",
            "Transparent thermal proxy; no authoritative dynamic CTS equation was found.",
        ),
        "EGT1_C": _entry(
            "tier2_assumption",
            "Rotax 915 i A documentation and Stage 4 synthetic cylinder offsets",
            "Cylinder offsets are synthetic and intentionally small.",
        ),
        "EGT2_C": _entry(
            "tier2_assumption",
            "Rotax 915 i A documentation and Stage 4 synthetic cylinder offsets",
            "Cylinder offsets are synthetic and intentionally small.",
        ),
        "EGT3_C": _entry(
            "tier2_assumption",
            "Rotax 915 i A documentation and Stage 4 synthetic cylinder offsets",
            "Cylinder offsets are synthetic and intentionally small.",
        ),
        "EGT4_C": _entry(
            "tier2_assumption",
            "Rotax 915 i A documentation and Stage 4 synthetic cylinder offsets",
            "Cylinder offsets are synthetic and intentionally small.",
        ),
        "EGT_mean_C": _entry(
            "tier2_proxy",
            "Rotax 915 i A documentation",
            "Baseline EGT proxy derived from power, RPM, MAT and plenum pressure.",
        ),
        "EGT_max_C": _entry(
            "tier2_proxy",
            "Rotax 915 i A documentation",
            "Derived from the synthetic cylinder EGT series.",
        ),
        "EGT_min_C": _entry(
            "tier2_proxy",
            "Rotax 915 i A documentation",
            "Derived from the synthetic cylinder EGT series.",
        ),
        "EGT_spread_C": _entry(
            "tier2_proxy",
            "Rotax operating-limit documentation and fuel-flow-dependent EGT spread guidance",
            "Spread is limited by documented fuel-flow-dependent bounds using a transparent proxy.",
        ),
        "oil_pressure_bar": _entry(
            "tier2_proxy",
            "Rotax Operator Manual Section 2.1 and startup procedure guidance",
            "Simple RPM/load/temperature proxy constrained by the documented oil-pressure envelope.",
        ),
        "oil_temperature_C": _entry(
            "tier2_proxy",
            "Rotax Operator Manual warm-up, takeoff and maximum temperature guidance",
            "Simple transparent thermal proxy constrained by documented oil-temperature limits.",
        ),
        "battery_voltage_V": _entry(
            "tier2_proxy",
            "Rotax IM-915 i A battery and EMS voltage limits",
            "Simple electrical proxy constrained by the EMS and battery voltage bounds.",
        ),
        "battery_soc_pct": _entry(
            "tier2_proxy",
            "Rotax IM-915 i A battery capacity guidance",
            "State-of-charge proxy derived from the modeled electrical state.",
        ),
        "generator_A_current_A": _entry(
            "official_graph_digitized",
            "Rotax IM-915 i A Figure 3.5",
            "Digitized at 135 C oil temperature; approximate visual accuracy about +/-2 A and +/-100 RPM.",
        ),
        "generator_B_current_A": _entry(
            "official_graph_digitized",
            "Rotax IM-915 i A Figure 3.5",
            "Digitized at 135 C oil temperature; approximate visual accuracy about +/-2 A and +/-100 RPM.",
        ),
        "generator_voltage_V": _entry(
            "official_specification",
            "Rotax IM-915 i A generator and EMS voltage limits",
            "System-level voltage proxy constrained to the documented range.",
        ),
        "generator_power_W": _entry(
            "official_specification",
            "Rotax IM-915 i A airframe terminal and EMS power limits",
            "System-level power proxy capped by documented electrical limits.",
        ),
        "generator_switch_ready": _entry(
            "official_procedure",
            "Rotax IM-915 i A generator switching procedure",
            "Generator becomes ready above approximately 2400 RPM.",
        ),
        "generator_switch_latched": _entry(
            "official_procedure",
            "Rotax IM-915 i A generator switching procedure",
            "Hold time of 8 seconds is modeled explicitly.",
        ),
        "generator_switch_threshold_rpm": _entry(
            "official_procedure",
            "Rotax IM-915 i A generator switching procedure",
            "Threshold around 2400 RPM.",
        ),
        "generator_switch_hold_time_s": _entry(
            "official_procedure",
            "Rotax IM-915 i A generator switching procedure",
            "Eight second hold time.",
        ),
        "vibration_amplitude": _entry(
            "tier2_proxy",
            "Stage 4 synthetic engine-order proxy",
            "Synthetic harmonic amplitude driven by RPM and load.",
        ),
        "vibration_frequency_Hz": _entry(
            "tier2_proxy",
            "Engine-order definition",
            "Fundamental crank frequency equals RPM/60.",
        ),
        "vibration_1x": _entry(
            "tier2_proxy",
            "Stage 4 synthetic engine-order proxy",
            "1x harmonic amplitude proxy.",
        ),
        "vibration_2x": _entry(
            "tier2_proxy",
            "Stage 4 synthetic engine-order proxy",
            "2x harmonic amplitude proxy.",
        ),
        "vibration_3x": _entry(
            "tier2_proxy",
            "Stage 4 synthetic engine-order proxy",
            "3x harmonic amplitude proxy.",
        ),
    }

    stage4_source_types = (
        "official_limit",
        "official_specification",
        "official_graph_digitized",
        "official_procedure",
        "tier2_proxy",
        "tier2_assumption",
    )

    return HealthState(
        rpm=rpm,
        throttle_pct=throttle_pct,
        altitude_ft=altitude_ft,
        ambient_temp_C=ambient_temp_C,
        power_kW=power_kW,
        torque_Nm=torque_Nm,
        fuelflow_kgh=fuelflow_kgh,
        p_plenum_bar=p_plenum_bar,
        t_plenum_K=t_plenum_K,
        coolant_temp_C=coolant_temp_C,
        EGT1_C=egt_values[0],
        EGT2_C=egt_values[1],
        EGT3_C=egt_values[2],
        EGT4_C=egt_values[3],
        EGT_mean_C=egt_mean_C,
        EGT_max_C=egt_max_C,
        EGT_min_C=egt_min_C,
        EGT_spread_C=egt_spread_C,
        oil_pressure_bar=oil_pressure_bar,
        oil_temperature_C=oil_temperature_C,
        battery_voltage_V=battery_voltage_V,
        battery_soc_pct=battery_soc_pct,
        generator_A_current_A=generator_A_current_A,
        generator_B_current_A=generator_B_current_A,
        generator_voltage_V=generator_voltage_V,
        generator_power_W=generator_power_W,
        generator_switch_ready=gen_switch.ready,
        generator_switch_latched=gen_switch.latched,
        generator_switch_threshold_rpm=gen_switch.threshold_rpm,
        generator_switch_hold_time_s=gen_switch.hold_time_s,
        vibration_amplitude=vibration_amplitude,
        vibration_frequency_Hz=vibration_frequency_Hz,
        vibration_1x=vibration_1x,
        vibration_2x=vibration_2x,
        vibration_3x=vibration_3x,
        production_source=CSV_AUTHORITATIVE,
        stage4_source_types=stage4_source_types,
        provenance=provenance,
    )


def main() -> int:
    print("Stage 4 health parameter layer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
