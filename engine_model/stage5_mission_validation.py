"""
Stage 5 mission validation.

This script generates the mission CSVs for every supported Stage 5 mission
type and checks phase ordering, bounded state generation, deterministic
reproducibility, and the Stage 3 integration points that must remain unchanged.
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
    from stage5_mission_generator import (
        MISSION_PHASES,
        NormalMissionGenerator,
        write_mission_csv,
    )
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
    from engine_model.stage5_mission_generator import (
        MISSION_PHASES,
        NormalMissionGenerator,
        write_mission_csv,
    )


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "stage5_outputs"

MISSION_CASES = [
    (
        MISSION_TYPE_NORMAL,
        build_normal_mission_config,
        OUTPUT_DIR / "normal_mission_validation.csv",
    ),
    (
        MISSION_TYPE_HIGH_ALTITUDE,
        build_high_altitude_mission_config,
        OUTPUT_DIR / "high_altitude_mission_validation.csv",
    ),
    (
        MISSION_TYPE_ENDURANCE,
        build_endurance_mission_config,
        OUTPUT_DIR / "endurance_mission_validation.csv",
    ),
    (
        MISSION_TYPE_HOT_WEATHER,
        build_hot_weather_mission_config,
        OUTPUT_DIR / "hot_weather_mission_validation.csv",
    ),
    (
        MISSION_TYPE_HIGH_POWER,
        build_high_power_mission_config,
        OUTPUT_DIR / "high_power_mission_validation.csv",
    ),
    (
        MISSION_TYPE_RAPID_THROTTLE,
        build_rapid_throttle_mission_config,
        OUTPUT_DIR / "rapid_throttle_mission_validation.csv",
    ),
]


def _assert_close(name: str, actual: float, expected: float, *, abs_tol: float = 1e-9) -> None:
    if not isclose(actual, expected, rel_tol=0.0, abs_tol=abs_tol):
        raise AssertionError(f"{name} mismatch: actual={actual}, expected={expected}")


def _assert_finite(name: str, value: float) -> None:
    if value is None or not isfinite(float(value)):
        raise AssertionError(f"{name} must be finite")


def _phase_index_map() -> dict[str, int]:
    return {phase: idx for idx, phase in enumerate(MISSION_PHASES)}


def _validate_common_rows(rows) -> None:
    if not rows:
        raise AssertionError("Mission generator returned no rows")

    phases = [row.phase for row in rows]
    index_map = _phase_index_map()
    if phases[0] != "TAKEOFF":
        raise AssertionError("Mission must start in TAKEOFF")
    if phases[-1] != "IDLE/LANDING":
        raise AssertionError("Mission must end in IDLE/LANDING")
    observed_indices = [index_map[phase] for phase in phases]
    if observed_indices != sorted(observed_indices):
        raise AssertionError("Mission phases must be ordered TAKEOFF -> CLIMB -> CRUISE -> DESCENT -> IDLE/LANDING")

    for row in rows:
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
        ):
            _assert_finite(field_name, getattr(row, field_name))
        if row.altitude_ft < 0.0 or row.altitude_m < 0.0:
            raise AssertionError("Altitude must be non-negative")
        if row.rpm < 0.0 or row.rpm > 5800.0 + 1e-9:
            raise AssertionError("RPM out of bounds")
        if row.throttle_pct < 56.5 - 1e-9 or row.throttle_pct > 100.0 + 1e-9:
            raise AssertionError("Throttle out of bounds")
        if row.ambient_pressure_hPa <= 0.0:
            raise AssertionError("Ambient pressure must be positive")
        if row.power_kW <= 0.0 or row.fuelflow_kgh <= 0.0:
            raise AssertionError("Stage 3 outputs must be positive")

    climb_rows = [row for row in rows if row.phase == "CLIMB"]
    cruise_rows = [row for row in rows if row.phase == "CRUISE"]
    descent_rows = [row for row in rows if row.phase == "DESCENT"]
    if not climb_rows or not cruise_rows or not descent_rows:
        raise AssertionError("All mission phases must be present")

    if climb_rows[-1].altitude_ft <= climb_rows[0].altitude_ft:
        raise AssertionError("Altitude must increase during climb")
    cruise_span = max(row.altitude_ft for row in cruise_rows) - min(row.altitude_ft for row in cruise_rows)
    if cruise_span > 100.0:
        raise AssertionError("Altitude must remain approximately stable during cruise")
    if descent_rows[-1].altitude_ft >= descent_rows[0].altitude_ft:
        raise AssertionError("Altitude must decrease during descent")

    max_rpm_step = max(abs(rows[idx + 1].rpm - rows[idx].rpm) for idx in range(len(rows) - 1))
    max_throttle_step = max(abs(rows[idx + 1].throttle_pct - rows[idx].throttle_pct) for idx in range(len(rows) - 1))
    if max_rpm_step > 1500.0:
        raise AssertionError("RPM transition is too abrupt")
    if max_throttle_step > 35.0:
        raise AssertionError("Throttle transition is too abrupt")


def _validate_determinism(config) -> None:
    rows_a = NormalMissionGenerator(config).generate_rows()
    rows_b = NormalMissionGenerator(config).generate_rows()
    if [row.to_dict() for row in rows_a] != [row.to_dict() for row in rows_b]:
        raise AssertionError("Fixed seed did not reproduce identical mission output")


def _validate_seed_variation(builder) -> None:
    config_a = builder(random_seed=101)
    config_b = builder(random_seed=102)
    rows_a = NormalMissionGenerator(config_a).generate_rows()
    rows_b = NormalMissionGenerator(config_b).generate_rows()
    if [row.to_dict() for row in rows_a] == [row.to_dict() for row in rows_b]:
        raise AssertionError("Different seeds should produce different valid mission output")


def _validate_stage3_case_2151() -> None:
    model = Stage13HybridEngineOutput()
    state = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)
    _assert_close("power_kW", state.power_kW, 15.36454167, abs_tol=1e-8)
    _assert_close("torque_Nm", state.torque_Nm, 48.90685510, abs_tol=1e-8)
    _assert_close("fuelflow_kgh", state.fuelflow_kgh, 6.02, abs_tol=1e-8)
    _assert_close("p_plenum_bar", state.p_plenum_bar, 0.6256, abs_tol=1e-8)
    _assert_close("t_plenum_K", state.t_plenum_K, 289.85, abs_tol=1e-8)


def _validate_normal_mission(config, rows) -> None:
    _validate_determinism(config)
    _validate_seed_variation(build_normal_mission_config)
    if rows[0].mission_type != MISSION_TYPE_NORMAL:
        raise AssertionError("Normal mission type mismatch")


def _validate_high_altitude_mission(config, rows) -> None:
    if max(row.altitude_ft for row in rows) > 23000.0 + 1e-9:
        raise AssertionError("High-altitude mission exceeded the official altitude limit")
    if not any(row.altitude_ft < 15000.0 for row in rows) or not any(row.altitude_ft >= 15000.0 for row in rows):
        raise AssertionError("High-altitude mission must explicitly cross the 15000 ft region")
    if max(row.power_kW for row in rows if row.altitude_ft >= 15000.0) >= 99.0:
        raise AssertionError("High-altitude mission should not claim continuous 99 kW capability above critical altitude")


def _validate_endurance_mission(config, rows) -> None:
    cruise_rows = [row for row in rows if row.phase == "CRUISE"]
    if not cruise_rows:
        raise AssertionError("Endurance mission must include cruise rows")
    cruise_rpm_span = max(row.rpm for row in cruise_rows) - min(row.rpm for row in cruise_rows)
    cruise_throttle_span = max(row.throttle_pct for row in cruise_rows) - min(row.throttle_pct for row in cruise_rows)
    if cruise_rpm_span > 300.0:
        raise AssertionError("Endurance cruise RPM variation is too large")
    if cruise_throttle_span > 10.0:
        raise AssertionError("Endurance cruise throttle variation is too large")


def _validate_hot_weather_mission(config, rows) -> None:
    expected_offset = float(config.ambient_temperature_offset_C)
    if expected_offset not in (15.0, 30.0):
        raise AssertionError("Hot-weather mission should use a supported temperature offset")
    for row in rows:
        offset = row.ambient_temperature_C - isa_temp_c(row.altitude_ft)
        if abs(offset - expected_offset) > 1e-8:
            raise AssertionError("Hot-weather temperature offset must be applied exactly once")


def _validate_high_power_mission(config, rows, generator) -> None:
    if generator.schedule.takeoff_duration_s > 300.0 + 1e-9:
        raise AssertionError("High-power takeoff duration exceeds the 5-minute limit")
    if rows[0].rpm != 5800.0 or rows[0].throttle_pct != 100.0:
        raise AssertionError("High-power mission must start at 5800 RPM and 100% throttle")
    if max(row.rpm for row in rows if row.phase == "TAKEOFF") < 5500.0:
        raise AssertionError("High-power takeoff should remain near the certified high-power band")


def _validate_rapid_throttle_mission(config, rows) -> None:
    throttle_steps = [rows[idx + 1].throttle_pct - rows[idx].throttle_pct for idx in range(len(rows) - 1)]
    rpm_steps = [rows[idx + 1].rpm - rows[idx].rpm for idx in range(len(rows) - 1)]
    if max(abs(step) for step in throttle_steps) > 35.0:
        raise AssertionError("Rapid-throttle mission has an unrealistic throttle jump")
    if max(abs(step) for step in rpm_steps) > 1500.0:
        raise AssertionError("Rapid-throttle mission has an unrealistic RPM jump")
    sign_changes = 0
    previous_sign = 0
    for step in throttle_steps:
        sign = 1 if step > 0 else -1 if step < 0 else 0
        if sign and previous_sign and sign != previous_sign:
            sign_changes += 1
        if sign:
            previous_sign = sign
    if sign_changes < 2:
        raise AssertionError("Rapid-throttle mission should contain repeated throttle ramps")


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
    print("STAGE 5 ALL-MISSION VALIDATION")
    print("=" * 94)

    for mission_type, builder, csv_path in MISSION_CASES:
        config = builder()
        generator = NormalMissionGenerator(config)
        rows = generator.generate_rows()
        _validate_common_rows(rows)

        if mission_type == MISSION_TYPE_NORMAL:
            _validate_normal_mission(config, rows)
        elif mission_type == MISSION_TYPE_HIGH_ALTITUDE:
            _validate_high_altitude_mission(config, rows)
        elif mission_type == MISSION_TYPE_ENDURANCE:
            _validate_endurance_mission(config, rows)
        elif mission_type == MISSION_TYPE_HOT_WEATHER:
            _validate_hot_weather_mission(config, rows)
        elif mission_type == MISSION_TYPE_HIGH_POWER:
            _validate_high_power_mission(config, rows, generator)
        elif mission_type == MISSION_TYPE_RAPID_THROTTLE:
            _validate_rapid_throttle_mission(config, rows)

        csv_path = write_mission_csv(rows, csv_path)
        print(f"{mission_type}: {csv_path} ({len(rows)} rows)")

    _validate_stage3_case_2151()
    _run_existing_regressions()
    print("Stage 1-4 regressions: PASS")
    print("Stage 3 case 2151: PASS")
    print("Stage 5 all-mission validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
