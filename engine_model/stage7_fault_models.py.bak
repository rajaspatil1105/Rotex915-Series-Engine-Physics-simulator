"""
Stage 7 abnormal-state transformation layer.

This module does NOT modify Stage 5. It takes one validated Stage-5 telemetry
mission and applies a documented, reproducible fault model to the Stage-4
health/telemetry state.

Important:
- Physical faults modify existing Tier-2 proxy telemetry coherently.
- Sensor drift modifies only the selected measured channel.
- Fuel pressure is a new Stage-7-only modeled channel with a documented
  3.0 bar healthy baseline.
- Limit flags are derived after fault generation.
"""

from __future__ import annotations

from dataclasses import replace
from dataclasses import is_dataclass
from typing import Iterable
import math
import random

from engine_model.stage5_simulation_pipeline import TelemetryRecord
from engine_model.stage7_fault_config import (
    EGT_SPLIT_LIMIT_HIGH_FUELFLOW_C,
    EGT_SPLIT_LIMIT_LOW_FUELFLOW_C,
    FUEL_PRESSURE_NORMAL_MIN_BAR,
    FUEL_PRESSURE_NORMAL_MAX_BAR,
    FUEL_PRESSURE_TRANSIENT_MAX_DURATION_S,
    FUEL_PRESSURE_TRANSIENT_MAX_BAR,
    FUEL_PRESSURE_TRANSIENT_MIN_BAR,
    MAX_COOLANT_TEMP_C,
    MAX_EGT_C,
    MAX_OIL_TEMP_C,
    MISFIRE_COMBUSTION_EFFECT,
    COOLING_EFFECTIVENESS_LOSS,
    LUBRICATION_FLOW_LOSS,
    SENSOR_DRIFT_FRACTION,
    FUEL_PRESSURE_FAULT_LOW_BAR,
)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _smoothstep(x: float) -> float:
    x = _clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _fault_envelope(
    time_s: float,
    start_s: float,
    end_s: float,
    ramp_fraction: float = 0.20,
) -> float:
    """0 outside fault, ramps in/out smoothly, 1 at full severity."""
    if end_s <= start_s or time_s < start_s or time_s > end_s:
        return 0.0

    duration = end_s - start_s
    ramp = max(1.0, duration * ramp_fraction)

    if time_s < start_s + ramp:
        return _smoothstep((time_s - start_s) / ramp)

    if time_s > end_s - ramp:
        return _smoothstep((end_s - time_s) / ramp)

    return 1.0


def choose_fault_window(
    rows: list[TelemetryRecord],
    rng: random.Random,
) -> tuple[float, float]:
    if not rows:
        raise ValueError("Cannot choose fault window from empty mission.")

    t0 = float(rows[0].time_s)
    t1 = float(rows[-1].time_s)

    if t1 <= t0:
        return t0, t1

    duration = t1 - t0

    # Assumption: fault starts in the middle portion of a mission and lasts
    # long enough to contain a useful temporal signature.
    start_fraction = rng.uniform(0.30, 0.55)
    duration_fraction = rng.uniform(0.25, 0.45)

    start = t0 + duration * start_fraction
    end = min(t1, start + duration * duration_fraction)

    return start, end


def _healthy_fuel_pressure_bar(
    row: TelemetryRecord,
    rng: random.Random,
) -> float:
    """Stage-7-only healthy baseline around documented nominal ~3.0 bar.

    The 3.0 bar center is an engineering midpoint of the documented
    2.9-3.2 bar normal range. The +/-0.015 bar scatter is a simulation
    assumption, not a manufacturer tolerance.
    """
    return _clamp(3.0 + rng.uniform(-0.015, 0.015), 2.90, 3.10)


def _annotate_row(
    row: TelemetryRecord,
    *,
    engine_id: str,
    fault_type: str,
    severity: str,
    fault_start_s: float,
    fault_end_s: float,
    envelope: float,
    fuel_pressure_bar: float,
    limit_exceeded: bool,
    limit_parameter: str,
    limit_value: float | None,
    true_sensor_value: float | None,
    measured_sensor_value: float | None,
) -> dict[str, object]:
    data = row.to_dict()

    data.update(
        {
            "engine_id": engine_id,
            "fault_present": True,
            "fault_type": fault_type,
            "fault_category": (
                "sensor" if fault_type == "sensor_drift"
                else "physical_proxy"
            ),
            "fault_severity": severity,
            "fault_start_time_s": fault_start_s,
            "fault_end_time_s": fault_end_s,
            "fault_envelope": envelope,
            "fuel_pressure_bar": fuel_pressure_bar,
            "limit_exceeded": limit_exceeded,
            "limit_parameter": limit_parameter,
            "limit_value": limit_value,
            "true_sensor_value": true_sensor_value,
            "measured_sensor_value": measured_sensor_value,
        }
    )
    return data


def apply_fault(
    rows: Iterable[TelemetryRecord],
    *,
    engine_id: str,
    fault_type: str,
    severity: str,
    seed: int,
    sensor_channel: str = "oil_temperature_C",
) -> list[dict[str, object]]:
    """Apply one reproducible Stage-7 fault to one healthy mission."""

    rows = list(rows)
    if not rows:
        raise ValueError("Cannot fault an empty mission.")

    if fault_type not in {
        "misfire",
        "cooling_degradation",
        "lubrication_degradation",
        "sensor_drift",
        "fuel_pressure_deviation",
    }:
        raise ValueError(f"Unsupported Stage-7 fault: {fault_type}")

    if severity not in {"mild", "moderate", "severe"}:
        raise ValueError(f"Unsupported severity: {severity}")

    rng = random.Random(seed)
    start_s, end_s = choose_fault_window(rows, rng)

    output: list[dict[str, object]] = []

    for row in rows:
        t = float(row.time_s)
        env = _fault_envelope(t, start_s, end_s)

        # Copy baseline values.
        egt = [
            float(row.EGT1_C),
            float(row.EGT2_C),
            float(row.EGT3_C),
            float(row.EGT4_C),
        ]
        coolant = float(row.coolant_temp_C)
        oil_pressure = float(row.oil_pressure_bar)
        oil_temp = float(row.oil_temperature_C)
        vibration = float(row.vibration_amplitude)

        # Stage-7-only fuel-pressure state.
        healthy_fuel_pressure = _healthy_fuel_pressure_bar(row, rng)
        fuel_pressure = healthy_fuel_pressure

        true_sensor_value = None
        measured_sensor_value = None

        # ---------------------------------------------------------------
        # MISFIRE
        # ---------------------------------------------------------------
        if fault_type == "misfire":
            effect = MISFIRE_COMBUSTION_EFFECT[severity] * env

            # Deterministic cylinder selection per mission.
            # The same cylinder is affected throughout the event.
            affected = (seed % 4)

            # Proxy: an underperforming cylinder loses EGT relative to the
            # healthy state; spread and vibration rise as consequences.
            egt[affected] = egt[affected] * (1.0 - 0.70 * effect)

            # Small coherent increase in vibration proxy.
            vibration *= 1.0 + 0.80 * effect

        # ---------------------------------------------------------------
        # COOLING DEGRADATION
        # ---------------------------------------------------------------
        elif fault_type == "cooling_degradation":
            loss = COOLING_EFFECTIVENESS_LOSS[severity] * env

            # Existing Stage-4 coolant temperature is a thermal proxy.
            # Approximate additional thermal rise from reduced rejection.
            thermal_headroom = max(0.0, 120.0 - coolant)
            coolant += thermal_headroom * (0.35 * loss)

            # Oil temperature follows the same degraded heat-rejection trend.
            oil_headroom = max(0.0, 130.0 - oil_temp)
            oil_temp += oil_headroom * (0.20 * loss)

        # ---------------------------------------------------------------
        # LUBRICATION DEGRADATION
        # ---------------------------------------------------------------
        elif fault_type == "lubrication_degradation":
            loss = LUBRICATION_FLOW_LOSS[severity] * env

            # Reduce pressure relative to the existing proxy.
            oil_pressure *= 1.0 - loss

            # Increased thermal burden from reduced lubrication.
            oil_temp += max(0.0, 130.0 - oil_temp) * (0.15 * loss)

            # Mechanical distress proxy.
            vibration *= 1.0 + 0.25 * loss

        # ---------------------------------------------------------------
        # SENSOR DRIFT
        # ---------------------------------------------------------------
        elif fault_type == "sensor_drift":
            if not hasattr(row, sensor_channel):
                raise ValueError(
                    f"Sensor channel {sensor_channel!r} does not exist."
                )

            true_sensor_value = float(getattr(row, sensor_channel))
            drift = SENSOR_DRIFT_FRACTION[severity] * env
            measured_sensor_value = true_sensor_value * (1.0 + drift)

        # ---------------------------------------------------------------
        # FUEL PRESSURE DEVIATION
        # ---------------------------------------------------------------
        elif fault_type == "fuel_pressure_deviation":
            target = FUEL_PRESSURE_FAULT_LOW_BAR[severity]
            fuel_pressure = (
                healthy_fuel_pressure * (1.0 - env)
                + target * env
            )

        # ---------------------------------------------------------------
        # Recalculate derived EGT values after fault.
        # ---------------------------------------------------------------
        egt_min = min(egt)
        egt_max = min(MAX_EGT_C, max(egt))
        egt_mean = sum(egt) / 4.0
        egt_spread = egt_max - egt_min

        # Sensor drift intentionally changes ONLY the measured channel.
        if fault_type == "sensor_drift":
            measured_sensor_value = float(measured_sensor_value)

        # Determine documented limit flags.
        limit_parameter = ""
        limit_value: float | None = None
        exceeded = False

        if coolant > MAX_COOLANT_TEMP_C:
            exceeded = True
            limit_parameter = "coolant_temp_C"
            limit_value = MAX_COOLANT_TEMP_C
        elif oil_temp > MAX_OIL_TEMP_C:
            exceeded = True
            limit_parameter = "oil_temperature_C"
            limit_value = MAX_OIL_TEMP_C
        elif egt_max > MAX_EGT_C:
            exceeded = True
            limit_parameter = "EGT_max_C"
            limit_value = MAX_EGT_C
        elif (
            fuel_pressure < FUEL_PRESSURE_NORMAL_MIN_BAR
            or fuel_pressure > FUEL_PRESSURE_NORMAL_MAX_BAR
        ):
            exceeded = True
            limit_parameter = "fuel_pressure_bar"
            limit_value = (
                FUEL_PRESSURE_NORMAL_MIN_BAR
                if fuel_pressure < FUEL_PRESSURE_NORMAL_MIN_BAR
                else FUEL_PRESSURE_NORMAL_MAX_BAR
            )

        # Apply measurement drift to the actual row field only.
        modified = replace(
            row,
            coolant_temp_C=coolant,
            EGT1_C=egt[0],
            EGT2_C=egt[1],
            EGT3_C=egt[2],
            EGT4_C=egt[3],
            EGT_mean_C=egt_mean,
            EGT_max_C=egt_max,
            EGT_min_C=egt_min,
            EGT_spread_C=egt_spread,
            oil_pressure_bar=oil_pressure,
            oil_temperature_C=oil_temp,
            vibration_amplitude=vibration,
            vibration_1x=vibration,
            vibration_2x=vibration * 0.6,
            vibration_3x=vibration * 0.4,
        )

        if fault_type == "sensor_drift":
            measured_sensor_value = float(measured_sensor_value)
            modified = replace(
                modified,
                **{sensor_channel: measured_sensor_value},
            )

        output.append(
            _annotate_row(
                modified,
                engine_id=engine_id,
                fault_type=fault_type,
                severity=severity,
                fault_start_s=start_s,
                fault_end_s=end_s,
                envelope=env,
                fuel_pressure_bar=fuel_pressure,
                limit_exceeded=exceeded,
                limit_parameter=limit_parameter,
                limit_value=limit_value,
                true_sensor_value=true_sensor_value,
                measured_sensor_value=measured_sensor_value,
            )
        )

    return output


def apply_limit_labels(
    rows: Iterable[TelemetryRecord | dict[str, object]],
    *,
    fault_present: bool = False,
) -> list[dict[str, object]]:
    """Apply operating-limit labels without injecting a fault."""

    output = []

    for row in rows:
        data = row.to_dict() if hasattr(row, "to_dict") else dict(row)

        coolant = float(data["coolant_temp_C"])
        oil_temp = float(data["oil_temperature_C"])
        egt_max = float(data["EGT_max_C"])
        fuel_pressure = (
            float(data["fuel_pressure_bar"])
            if "fuel_pressure_bar" in data
            else 3.0
        )

        exceeded = False
        parameter = ""
        value = None

        if coolant > MAX_COOLANT_TEMP_C:
            exceeded, parameter, value = True, "coolant_temp_C", MAX_COOLANT_TEMP_C
        elif oil_temp > MAX_OIL_TEMP_C:
            exceeded, parameter, value = True, "oil_temperature_C", MAX_OIL_TEMP_C
        elif egt_max > MAX_EGT_C:
            exceeded, parameter, value = True, "EGT_max_C", MAX_EGT_C
        elif not (
            FUEL_PRESSURE_NORMAL_MIN_BAR
            <= fuel_pressure
            <= FUEL_PRESSURE_NORMAL_MAX_BAR
        ):
            exceeded = True
            parameter = "fuel_pressure_bar"
            value = (
                FUEL_PRESSURE_NORMAL_MIN_BAR
                if fuel_pressure < FUEL_PRESSURE_NORMAL_MIN_BAR
                else FUEL_PRESSURE_NORMAL_MAX_BAR
            )

        data["fault_present"] = bool(fault_present)
        data["limit_exceeded"] = exceeded
        data["limit_parameter"] = parameter
        data["limit_value"] = value
        output.append(data)

    return output
