"""
Stage 5 mission-to-telemetry simulation pipeline.

This module orchestrates the existing Stage 5 mission generator, the Stage 1.3
calibrated engine-output layer, and the Stage 4 health layer into a single
healthy telemetry stream.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from stage1_3_hybrid_engine_output import Stage13HybridEngineOutput
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput

try:
    from stage4_health_parameters import HealthState, get_health_state, update_generator_switch_timer
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage4_health_parameters import HealthState, get_health_state, update_generator_switch_timer

try:
    from stage5_mission_config import MissionConfig
    from stage5_mission_generator import MissionState, NormalMissionGenerator
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage5_mission_config import MissionConfig
    from engine_model.stage5_mission_generator import MissionState, NormalMissionGenerator


TELEMETRY_FIELDNAMES = [
    "time_s",
    "mission_id",
    "mission_type",
    "phase",
    "random_seed",
    "model_version",
    "altitude_ft",
    "altitude_m",
    "ambient_temperature_C",
    "ambient_pressure_hPa",
    "throttle_pct",
    "rpm",
    "power_kW",
    "torque_Nm",
    "fuelflow_kgh",
    "p_plenum_bar",
    "t_plenum_K",
    "coolant_temp_C",
    "EGT1_C",
    "EGT2_C",
    "EGT3_C",
    "EGT4_C",
    "EGT_mean_C",
    "EGT_max_C",
    "EGT_min_C",
    "EGT_spread_C",
    "oil_pressure_bar",
    "oil_temperature_C",
    "battery_voltage_V",
    "battery_soc_pct",
    "generator_A_current_A",
    "generator_B_current_A",
    "generator_voltage_V",
    "generator_power_W",
    "generator_switch_ready",
    "generator_switch_latched",
    "generator_switch_threshold_rpm",
    "generator_switch_hold_time_s",
    "generator_time_above_threshold_s",
    "vibration_amplitude",
    "vibration_frequency_Hz",
    "vibration_1x",
    "vibration_2x",
    "vibration_3x",
    "engine_state_valid",
    "outside_calibrated_envelope",
    "extrapolation_used",
    "health_state_valid",
    "mission_generated_values",
    "stage3_values",
    "stage3_validation_status",
    "stage3_ambient_source",
    "stage4_production_source",
    "ambient_source",
]


@dataclass(frozen=True)
class TelemetryRecord:
    time_s: float
    mission_id: str
    mission_type: str
    phase: str
    random_seed: int
    model_version: str
    altitude_ft: float
    altitude_m: float
    ambient_temperature_C: float
    ambient_pressure_hPa: float
    throttle_pct: float
    rpm: float
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
    generator_time_above_threshold_s: float
    vibration_amplitude: float
    vibration_frequency_Hz: float
    vibration_1x: float
    vibration_2x: float
    vibration_3x: float
    engine_state_valid: bool
    outside_calibrated_envelope: bool
    extrapolation_used: bool
    health_state_valid: bool
    mission_generated_values: str
    stage3_values: str
    stage3_validation_status: str
    stage3_ambient_source: str
    stage4_production_source: str
    ambient_source: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _telemetry_record_from_states(
    mission_state: MissionState,
    engine_state,
    health_state: HealthState,
    *,
    generator_time_above_threshold_s: float,
) -> TelemetryRecord:
    return TelemetryRecord(
        time_s=float(mission_state.time_s),
        mission_id=mission_state.mission_id,
        mission_type=mission_state.mission_type,
        phase=mission_state.phase,
        random_seed=int(mission_state.random_seed if mission_state.random_seed is not None else 0),
        model_version=mission_state.model_version,
        altitude_ft=float(mission_state.altitude_ft),
        altitude_m=float(mission_state.altitude_m),
        ambient_temperature_C=float(mission_state.ambient_temperature_C),
        ambient_pressure_hPa=float(mission_state.ambient_pressure_hPa),
        throttle_pct=float(mission_state.throttle_pct),
        rpm=float(mission_state.rpm),
        power_kW=float(health_state.power_kW),
        torque_Nm=float(health_state.torque_Nm),
        fuelflow_kgh=float(health_state.fuelflow_kgh),
        p_plenum_bar=float(health_state.p_plenum_bar),
        t_plenum_K=float(health_state.t_plenum_K),
        coolant_temp_C=float(health_state.coolant_temp_C),
        EGT1_C=float(health_state.EGT1_C),
        EGT2_C=float(health_state.EGT2_C),
        EGT3_C=float(health_state.EGT3_C),
        EGT4_C=float(health_state.EGT4_C),
        EGT_mean_C=float(health_state.EGT_mean_C),
        EGT_max_C=float(health_state.EGT_max_C),
        EGT_min_C=float(health_state.EGT_min_C),
        EGT_spread_C=float(health_state.EGT_spread_C),
        oil_pressure_bar=float(health_state.oil_pressure_bar),
        oil_temperature_C=float(health_state.oil_temperature_C),
        battery_voltage_V=float(health_state.battery_voltage_V),
        battery_soc_pct=float(health_state.battery_soc_pct),
        generator_A_current_A=float(health_state.generator_A_current_A),
        generator_B_current_A=float(health_state.generator_B_current_A),
        generator_voltage_V=float(health_state.generator_voltage_V),
        generator_power_W=float(health_state.generator_power_W),
        generator_switch_ready=bool(health_state.generator_switch_ready),
        generator_switch_latched=bool(health_state.generator_switch_latched),
        generator_switch_threshold_rpm=float(health_state.generator_switch_threshold_rpm),
        generator_switch_hold_time_s=float(health_state.generator_switch_hold_time_s),
        generator_time_above_threshold_s=float(generator_time_above_threshold_s),
        vibration_amplitude=float(health_state.vibration_amplitude),
        vibration_frequency_Hz=float(health_state.vibration_frequency_Hz),
        vibration_1x=float(health_state.vibration_1x),
        vibration_2x=float(health_state.vibration_2x),
        vibration_3x=float(health_state.vibration_3x),
        engine_state_valid=True,
        outside_calibrated_envelope=bool(engine_state.extrapolated),
        extrapolation_used=bool(engine_state.extrapolated),
        health_state_valid=True,
        mission_generated_values=mission_state.mission_generated_values,
        stage3_values=mission_state.stage3_values,
        stage3_validation_status=mission_state.stage3_validation_status or "",
        stage3_ambient_source=engine_state.ambient_source,
        stage4_production_source=health_state.production_source,
        ambient_source=mission_state.ambient_source,
    )


def run_mission(
    mission_config: MissionConfig,
    *,
    engine_model: Stage13HybridEngineOutput | None = None,
) -> list[TelemetryRecord]:
    """
    Run the healthy Stage 5 pipeline and return complete telemetry rows.

    Stage 5 decides the operating conditions, Stage 3 computes the calibrated
    engine outputs, and Stage 4 converts those outputs into health telemetry.
    """

    model = engine_model or Stage13HybridEngineOutput()
    generator = NormalMissionGenerator(mission_config, engine_model=model)
    mission_rows = generator.generate_rows()

    telemetry_rows: list[TelemetryRecord] = []
    generator_time_above_threshold_s = 0.0
    previous_time_s = 0.0

    for index, mission_state in enumerate(mission_rows):
        dt_s = 0.0 if index == 0 else float(mission_state.time_s - previous_time_s)
        generator_time_above_threshold_s = update_generator_switch_timer(
            generator_time_above_threshold_s,
            mission_state.rpm,
            dt_s,
        )

        engine_state = model.get_engine_state(
            mission_state.rpm,
            mission_state.throttle_pct,
            mission_state.altitude_ft,
            mission_state.ambient_temperature_C,
        )
        health_state = get_health_state(
            engine_state,
            time_above_threshold_s=generator_time_above_threshold_s,
        )

        telemetry_rows.append(
            _telemetry_record_from_states(
                mission_state,
                engine_state,
                health_state,
                generator_time_above_threshold_s=generator_time_above_threshold_s,
            )
        )
        previous_time_s = float(mission_state.time_s)

    return telemetry_rows


def write_telemetry_csv(rows: Iterable[TelemetryRecord], csv_path: str | Path) -> Path:
    import csv

    rows = list(rows)
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TELEMETRY_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
    return csv_path
