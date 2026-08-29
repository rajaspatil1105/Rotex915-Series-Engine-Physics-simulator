"""
Stage 5 complete telemetry validation.

This script exercises the full healthy Stage 5 pipeline:
mission state -> Stage 3 -> Stage 4 -> telemetry row -> CSV.
"""

from __future__ import annotations

import subprocess
import sys
from math import isclose, isfinite
from pathlib import Path

try:
    from stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, isa_temp_c
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, isa_temp_c

try:
    from stage4_health_parameters import (
        GENERATOR_SWITCH_HOLD_TIME_S,
        GENERATOR_SWITCH_THRESHOLD_RPM,
        generator_switch_state,
        update_generator_switch_timer,
    )
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage4_health_parameters import (
        GENERATOR_SWITCH_HOLD_TIME_S,
        GENERATOR_SWITCH_THRESHOLD_RPM,
        generator_switch_state,
        update_generator_switch_timer,
    )

try:
    from stage5_mission_config import (
        MISSION_TYPE_ENDURANCE,
        MISSION_TYPE_HIGH_ALTITUDE,
        MISSION_TYPE_HIGH_POWER,
        MISSION_TYPE_HOT_WEATHER,
        MISSION_TYPE_NORMAL,
        MISSION_TYPE_RAPID_THROTTLE,
        build_endurance_mission_config,
        build_high_altitude_mission_config,
        build_high_power_mission_config,
        build_hot_weather_mission_config,
        build_normal_mission_config,
        build_rapid_throttle_mission_config,
    )
    from stage5_mission_generator import NormalMissionGenerator
    from stage5_simulation_pipeline import TELEMETRY_FIELDNAMES, run_mission, write_telemetry_csv
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage5_mission_config import (
        MISSION_TYPE_ENDURANCE,
        MISSION_TYPE_HIGH_ALTITUDE,
        MISSION_TYPE_HIGH_POWER,
        MISSION_TYPE_HOT_WEATHER,
        MISSION_TYPE_NORMAL,
        MISSION_TYPE_RAPID_THROTTLE,
        build_endurance_mission_config,
        build_high_altitude_mission_config,
        build_high_power_mission_config,
        build_hot_weather_mission_config,
        build_normal_mission_config,
        build_rapid_throttle_mission_config,
    )
    from engine_model.stage5_mission_generator import NormalMissionGenerator
    from engine_model.stage5_simulation_pipeline import TELEMETRY_FIELDNAMES, run_mission, write_telemetry_csv


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "stage5_outputs"

MISSION_CASES = [
    (MISSION_TYPE_NORMAL, build_normal_mission_config, OUTPUT_DIR / "normal_complete_telemetry.csv"),
    (MISSION_TYPE_HIGH_ALTITUDE, build_high_altitude_mission_config, OUTPUT_DIR / "high_altitude_complete_telemetry.csv"),
    (MISSION_TYPE_ENDURANCE, build_endurance_mission_config, OUTPUT_DIR / "endurance_complete_telemetry.csv"),
    (MISSION_TYPE_HOT_WEATHER, build_hot_weather_mission_config, OUTPUT_DIR / "hot_weather_complete_telemetry.csv"),
    (MISSION_TYPE_HIGH_POWER, build_high_power_mission_config, OUTPUT_DIR / "high_power_complete_telemetry.csv"),
    (MISSION_TYPE_RAPID_THROTTLE, build_rapid_throttle_mission_config, OUTPUT_DIR / "rapid_throttle_complete_telemetry.csv"),
]


def _assert_close(name: str, actual: float, expected: float, *, abs_tol: float = 1e-9) -> None:
    if not isclose(actual, expected, rel_tol=0.0, abs_tol=abs_tol):
        raise AssertionError(f"{name} mismatch: actual={actual}, expected={expected}")


def _assert_finite(name: str, value: float) -> None:
    if value is None or not isfinite(float(value)):
        raise AssertionError(f"{name} must be finite")


def _validate_schema(rows) -> None:
    if not rows:
        raise AssertionError("Telemetry generator returned no rows")
    if list(rows[0].to_dict().keys()) != TELEMETRY_FIELDNAMES:
        raise AssertionError("Telemetry schema does not match the expected field order")


def _validate_common_telemetry(rows, mission_type: str) -> None:
    last_time_s: float | None = None
    expected_timer_s = 0.0
    for row_index, row in enumerate(rows):
        if row.mission_type != mission_type:
            raise AssertionError("Mission type mismatch in telemetry row")
        if last_time_s is not None and row.time_s < last_time_s:
            raise AssertionError("Telemetry timestamps must be monotonically increasing")
        for field_name in (
            "time_s",
            "altitude_ft",
            "altitude_m",
            "ambient_temperature_C",
            "ambient_pressure_hPa",
            "rpm",
            "throttle_pct",
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
            "generator_switch_threshold_rpm",
            "generator_switch_hold_time_s",
            "generator_time_above_threshold_s",
            "vibration_amplitude",
            "vibration_frequency_Hz",
            "vibration_1x",
            "vibration_2x",
            "vibration_3x",
        ):
            _assert_finite(field_name, getattr(row, field_name))

        if not row.engine_state_valid or not row.health_state_valid:
            raise AssertionError("Telemetry rows must be healthy and engine-valid")
        if row.outside_calibrated_envelope or row.extrapolation_used:
            raise AssertionError("Healthy telemetry must not extrapolate outside the calibrated envelope")
        if row.mission_generated_values != "python_mission_generator":
            raise AssertionError("Mission provenance mismatch")
        if row.stage3_values != "csv_authoritative":
            raise AssertionError("Stage 3 provenance mismatch")
        if row.stage4_production_source != "calibrated_csv":
            raise AssertionError("Stage 4 provenance mismatch")
        if row.stage3_ambient_source != "explicit_input":
            raise AssertionError("Stage 3 ambient source must reflect the explicit Stage 5 input")
        if row.ambient_source != "python_generated_isa_plus_offset":
            raise AssertionError("Mission ambient source mismatch")

        dt_s = 0.0 if last_time_s is None else row.time_s - last_time_s
        if row.rpm >= GENERATOR_SWITCH_THRESHOLD_RPM:
            expected_timer_s += dt_s
        else:
            expected_timer_s = 0.0
        if abs(row.generator_time_above_threshold_s - expected_timer_s) > 1e-9:
            raise AssertionError(
                "Generator timer state is not continuous across telemetry rows "
                f"(row_index={row_index}, time_s={row.time_s}, rpm={row.rpm}, "
                f"stored={row.generator_time_above_threshold_s}, expected={expected_timer_s}, dt_s={dt_s})"
            )
        last_time_s = row.time_s

        expected_switch = generator_switch_state(row.rpm, time_above_threshold_s=row.generator_time_above_threshold_s)
        if row.generator_switch_ready != expected_switch.ready:
            raise AssertionError("Generator ready state mismatch")
        if row.generator_switch_latched != expected_switch.latched:
            raise AssertionError("Generator latched state mismatch")
        if abs(row.generator_switch_threshold_rpm - GENERATOR_SWITCH_THRESHOLD_RPM) > 1e-12:
            raise AssertionError("Generator threshold RPM mismatch")
        if abs(row.generator_switch_hold_time_s - GENERATOR_SWITCH_HOLD_TIME_S) > 1e-12:
            raise AssertionError("Generator hold time mismatch")

        if row.altitude_ft < 0.0 or row.altitude_m < 0.0:
            raise AssertionError("Altitude must be non-negative")
        if row.rpm < 0.0 or row.rpm > 5800.0 + 1e-9:
            raise AssertionError("RPM out of bounds")
        if row.throttle_pct < 56.5 - 1e-9 or row.throttle_pct > 100.0 + 1e-9:
            raise AssertionError("Throttle out of bounds")
        offset = row.ambient_temperature_C - isa_temp_c(row.altitude_ft)
        if mission_type == MISSION_TYPE_HOT_WEATHER:
            if not any(abs(offset - candidate) <= 1e-9 for candidate in (15.0, 30.0)):
                raise AssertionError("Hot-weather missions must apply a supported ambient offset exactly once")
        elif abs(offset) > 1e-9:
            raise AssertionError("Ambient temperature must follow the Stage 3 ISA convention")


def _validate_stage3_and_stage4_alignment(rows) -> None:
    model = Stage13HybridEngineOutput()
    for row in rows[:: max(1, len(rows) // 10)]:
        engine_state = model.get_engine_state(row.rpm, row.throttle_pct, row.altitude_ft, row.ambient_temperature_C)
        _assert_close("power_kW", row.power_kW, engine_state.power_kW, abs_tol=1e-8)
        _assert_close("torque_Nm", row.torque_Nm, engine_state.torque_Nm, abs_tol=1e-8)
        _assert_close("fuelflow_kgh", row.fuelflow_kgh, engine_state.fuelflow_kgh, abs_tol=1e-8)
        _assert_close("p_plenum_bar", row.p_plenum_bar, engine_state.p_plenum_bar, abs_tol=1e-8)
        _assert_close("t_plenum_K", row.t_plenum_K, engine_state.t_plenum_K, abs_tol=1e-8)


def _validate_generator_timer_cases() -> None:
    cases = [
        ("below_threshold", [(2390.0, 20.0)], False, 0.0),
        ("threshold_short", [(2500.0, 7.9)], False, 7.9),
        ("threshold_exact", [(2500.0, 8.0)], True, 8.0),
        ("above_then_drop", [(2500.0, 5.0), (2300.0, 1.0), (2500.0, 3.0)], False, 3.0),
        ("above_long", [(2500.0, 8.1)], True, 8.1),
    ]
    for label, steps, expected_latched, expected_timer in cases:
        timer = 0.0
        last_rpm = 0.0
        for rpm, dt_s in steps:
            timer = update_generator_switch_timer(timer, rpm, dt_s)
            last_rpm = rpm
        state = generator_switch_state(last_rpm, time_above_threshold_s=timer)
        if state.latched != expected_latched:
            raise AssertionError(f"Generator switch latch mismatch for {label}")
        _assert_close(f"{label}_timer", timer, expected_timer, abs_tol=1e-9)


def _validate_case_2151() -> None:
    model = Stage13HybridEngineOutput()
    state = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)
    _assert_close("power_kW", state.power_kW, 15.36454167, abs_tol=1e-8)
    _assert_close("torque_Nm", state.torque_Nm, 48.90685510, abs_tol=1e-8)
    _assert_close("fuelflow_kgh", state.fuelflow_kgh, 6.02, abs_tol=1e-8)
    _assert_close("p_plenum_bar", state.p_plenum_bar, 0.6256, abs_tol=1e-8)
    _assert_close("t_plenum_K", state.t_plenum_K, 289.85, abs_tol=1e-8)


def _run_existing_regressions() -> None:
    commands = [
        [sys.executable, "-m", "pytest", "test_stage_regressions.py"],
        [sys.executable, "engine_model/stage2_engine_state_smoke_validation.py"],
        [sys.executable, "engine_model/stage3_altitude_profile_validation.py"],
        [sys.executable, "engine_model/stage4_health_validation.py"],
    ]
    for cmd in commands:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(
                "Existing regression failed:\n"
                + "Command: "
                + " ".join(cmd)
                + "\n"
                + (result.stdout or "")
                + (result.stderr or "")
            )


def main() -> int:
    print("=" * 94)
    print("STAGE 5 COMPLETE TELEMETRY VALIDATION")
    print("=" * 94)

    for mission_type, builder, csv_path in MISSION_CASES:
        config = builder()
        rows = run_mission(config)
        _validate_schema(rows)
        _validate_common_telemetry(rows, mission_type)
        _validate_stage3_and_stage4_alignment(rows)
        csv_path = write_telemetry_csv(rows, csv_path)
        print(f"{mission_type}: {csv_path} ({len(rows)} rows)")

    _validate_generator_timer_cases()
    _validate_case_2151()
    _run_existing_regressions()
    print("Stage 1-4 regressions: PASS")
    print("Stage 3 case 2151: PASS")
    print("Generator timer validation: PASS")
    print("Stage 5 complete telemetry validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
