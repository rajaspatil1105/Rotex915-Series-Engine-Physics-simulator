"""
Stage 4 health layer validation.

Validation only:
- reuse the verified Stage 1.3/2 engine-state interface
- validate the new Stage 4 health telemetry layer
- do not modify production engine outputs or protected data files
"""

from __future__ import annotations

import hashlib
from math import isclose, isfinite
from pathlib import Path

try:
    from stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, torque_nm_from_power_kw
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, torque_nm_from_power_kw

try:
    from stage4_health_parameters import (
        EGT_SPREAD_LIMIT_HIGH_LPH_C,
        EGT_SPREAD_LIMIT_LOW_LPH_C,
        GENERATOR_A_CURVE,
        GENERATOR_B_CURVE,
        GENERATOR_GRAPH_CONDITION_C,
        GENERATOR_SWITCH_HOLD_TIME_S,
        GENERATOR_SWITCH_THRESHOLD_RPM,
        HealthState,
        egt_spread_limit_from_fuel_flow,
        generator_switch_state,
        get_health_state,
        lookup_digitized_generator_current,
        update_generator_switch_timer,
    )
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage4_health_parameters import (
        EGT_SPREAD_LIMIT_HIGH_LPH_C,
        EGT_SPREAD_LIMIT_LOW_LPH_C,
        GENERATOR_A_CURVE,
        GENERATOR_B_CURVE,
        GENERATOR_GRAPH_CONDITION_C,
        GENERATOR_SWITCH_HOLD_TIME_S,
        GENERATOR_SWITCH_THRESHOLD_RPM,
        HealthState,
        egt_spread_limit_from_fuel_flow,
        generator_switch_state,
        get_health_state,
        lookup_digitized_generator_current,
        update_generator_switch_timer,
    )


ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATTERNS = [
    "engine_model/stage1_2_*.py",
    "engine_model/wall_closed_compression_verified.py",
    "rotax_915is_performance_map.csv",
    "calibration/*.csv",
    "calibration/*.json",
    "config/rotax_915is_engine_parameters.csv",
    "config/rotax_915is_engine_parameters.md",
    "config/rotax_915is_missing_parameters.md",
]
ALLOWED_PROVENANCE_LABELS = {
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


def _assert_close(name: str, actual: float, expected: float, *, rel_tol: float = 1e-9, abs_tol: float = 1e-9) -> None:
    if not isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol):
        raise AssertionError(f"{name} mismatch: actual={actual}, expected={expected}")


def _assert_finite(name: str, value: float) -> None:
    if value is None or not isfinite(float(value)):
        raise AssertionError(f"{name} must be finite")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_protected_files() -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for pattern in PROTECTED_PATTERNS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                snapshot[str(path.relative_to(ROOT))] = _sha256(path)
    return snapshot


def _linear_expected(rpm: float, curve: dict[float, float]) -> float:
    points = sorted((float(k), float(v)) for k, v in curve.items())
    if rpm <= points[0][0]:
        return points[0][1]
    if rpm >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        if x0 <= rpm <= x1:
            frac = (rpm - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return points[-1][1]


def _print_health(prefix: str, state: HealthState) -> None:
    print(
        f"{prefix}: rpm={state.rpm:.1f}, throttle={state.throttle_pct:.1f}, alt_ft={state.altitude_ft:.1f}, "
        f"power_kW={state.power_kW:.6f}, torque_Nm={state.torque_Nm:.6f}, fuelflow_kgh={state.fuelflow_kgh:.6f}, "
        f"p_plenum_bar={state.p_plenum_bar:.4f}, t_plenum_K={state.t_plenum_K:.2f}, coolant_temp_C={state.coolant_temp_C:.2f}, "
        f"EGT_mean_C={state.EGT_mean_C:.2f}, EGT_spread_C={state.EGT_spread_C:.2f}, oil_pressure_bar={state.oil_pressure_bar:.2f}, "
        f"oil_temperature_C={state.oil_temperature_C:.2f}, battery_voltage_V={state.battery_voltage_V:.2f}, "
        f"battery_soc_pct={state.battery_soc_pct:.2f}, generator_A_current_A={state.generator_A_current_A:.2f}, "
        f"generator_B_current_A={state.generator_B_current_A:.2f}, generator_voltage_V={state.generator_voltage_V:.2f}, "
        f"generator_power_W={state.generator_power_W:.2f}, vibration_frequency_Hz={state.vibration_frequency_Hz:.2f}"
    )


def _validate_provenance(state: HealthState) -> None:
    expected_fields = [
        "rpm",
        "throttle_pct",
        "altitude_ft",
        "ambient_temp_C",
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
        "vibration_amplitude",
        "vibration_frequency_Hz",
        "vibration_1x",
        "vibration_2x",
        "vibration_3x",
    ]
    for field in expected_fields:
        if field not in state.provenance:
            raise AssertionError(f"Missing provenance for {field}")
        entry = state.provenance[field]
        if entry.label not in ALLOWED_PROVENANCE_LABELS:
            raise AssertionError(f"Unsupported provenance label for {field}: {entry.label}")
    if state.production_source != "calibrated_csv":
        raise AssertionError("Production source must remain calibrated_csv")


def _validate_limits_and_sanity(state: HealthState) -> None:
    for field in [
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
        "vibration_amplitude",
        "vibration_frequency_Hz",
        "vibration_1x",
        "vibration_2x",
        "vibration_3x",
    ]:
        _assert_finite(field, getattr(state, field))
    if state.coolant_temp_C > 120.0:
        raise AssertionError("coolant temperature exceeds documented normal maximum")
    if state.EGT_max_C > 950.0:
        raise AssertionError("EGT exceeds documented maximum")
    if state.oil_temperature_C < -20.0 or state.oil_temperature_C > 130.0:
        raise AssertionError("oil temperature outside documented bounds")
    if state.battery_voltage_V < 9.0 or state.battery_voltage_V > 14.5:
        raise AssertionError("battery voltage outside documented bounds")
    if state.generator_power_W > 420.0 + 1e-9:
        raise AssertionError("generator power exceeds documented system limit")
    if not isclose(state.vibration_frequency_Hz, state.rpm / 60.0, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("vibration 1x frequency must equal RPM/60")
    if not isclose(state.vibration_2x, state.vibration_1x * 0.6, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("2x vibration harmonic mismatch")
    if not isclose(state.vibration_3x, state.vibration_1x * 0.4, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("3x vibration harmonic mismatch")
    if state.generator_voltage_V < 9.0 or state.generator_voltage_V > 14.5:
        raise AssertionError("generator voltage outside documented bounds")


def _validate_known_csv_case(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 1 - Stage 1.3 engine-state stability:")
    known = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)
    _print_health("  stage1_3_case_2151", get_health_state(known, time_above_threshold_s=10.0))
    _assert_close("power_kW", known.power_kW, 15.36454167)
    _assert_close("torque_Nm", known.torque_Nm, 48.90685510)
    _assert_close("fuelflow_kgh", known.fuelflow_kgh, 6.02)
    _assert_close("p_plenum_bar", known.p_plenum_bar, 0.6256)
    _assert_close("t_plenum_K", known.t_plenum_K, 289.85)


def _validate_ambient_temperature_interface(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 1b - ambient-temperature interface:")
    canonical = model.get_engine_state(5800.0, 100.0, 22999.0)
    explicit = model.get_engine_state(5800.0, 100.0, 22999.0, -1.0)
    canonical_health = get_health_state(canonical, time_above_threshold_s=10.0)
    explicit_health = get_health_state(explicit, time_above_threshold_s=10.0)
    _print_health("  canonical_isa", canonical_health)
    _print_health("  explicit_minus_1C", explicit_health)
    if canonical.ambient_source != "isa_surrogate":
        raise AssertionError("Omitted ambient temperature must use the ISA surrogate")
    if explicit.ambient_source != "explicit_input":
        raise AssertionError("Explicit ambient temperature must be preserved")


def _validate_health_states(model: Stage13HybridEngineOutput) -> list[HealthState]:
    print("\nValidation 2 - health telemetry across low/medium/high points:")
    points = [
        ("sea_low", 3000.0, 56.5, 0.0, 15.0),
        ("sea_mid", 3000.0, 84.5, 0.0, 15.0),
        ("mid_alt", 4000.0, 84.5, 5997.0, -12.0),
        ("high_load", 5000.0, 94.1, 15000.0, -30.0),
        ("top_end", 5800.0, 100.0, 22999.0, None),
    ]
    states: list[HealthState] = []
    for name, rpm, throttle, alt, tamb in points:
        engine_state = model.get_engine_state(rpm, throttle, alt, tamb)
        health = get_health_state(engine_state, time_above_threshold_s=10.0)
        _print_health(f"  {name}", health)
        _validate_provenance(health)
        _validate_limits_and_sanity(health)
        _assert_close("engine_state_pass_through_power", health.power_kW, engine_state.power_kW)
        _assert_close("engine_state_pass_through_torque", health.torque_Nm, engine_state.torque_Nm)
        _assert_close("engine_state_pass_through_fuel", health.fuelflow_kgh, engine_state.fuelflow_kgh)
        _assert_close("engine_state_pass_through_plenum_p", health.p_plenum_bar, engine_state.p_plenum_bar)
        _assert_close("engine_state_pass_through_plenum_t", health.t_plenum_K, engine_state.t_plenum_K)
        states.append(health)
    return states


def _validate_throttle_response(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 3 - throttle response on a fixed RPM/altitude:")
    sea_level_rows = model.df.loc[
        (model.df["rpm"] == 3000.0) & (model.df["alt_ft"] == 0.0) & (model.df["t_amb_C"] == 15.0)
    ].sort_values("throttle_pct")
    throttle_levels = [56.5, 72.0, 84.5, 94.1, 100.0]
    sea_level_rows = sea_level_rows.loc[sea_level_rows["throttle_pct"].isin(throttle_levels)].sort_values("throttle_pct")
    if len(sea_level_rows) != len(throttle_levels):
        raise AssertionError("Expected throttle levels missing from sea-level validation set")
    previous = None
    for _, row in sea_level_rows.iterrows():
        state = get_health_state(
            model.get_engine_state(
                float(row["rpm"]),
                float(row["throttle_pct"]),
                float(row["alt_ft"]),
                float(row["t_amb_C"]),
            ),
            time_above_threshold_s=10.0,
        )
        _print_health(f"  throttle_{float(row['throttle_pct']):.1f}", state)
        if previous is not None:
            for field in ["power_kW", "torque_Nm", "fuelflow_kgh", "p_plenum_bar"]:
                if getattr(state, field) + 1e-9 < getattr(previous, field):
                    print(
                        f"    source reversal observed in {field}: {getattr(previous, field):.6f} -> {getattr(state, field):.6f}"
                    )
        previous = state


def _validate_generator_lookup() -> None:
    print("\nValidation 4 - generator lookup interpolation:")
    test_rpms = [2250.0, 2750.0, 3750.0, 5250.0, 5700.0]
    for rpm in test_rpms:
        for generator, curve in [("A", GENERATOR_A_CURVE), ("B", GENERATOR_B_CURVE)]:
            expected = _linear_expected(rpm, curve)
            actual = lookup_digitized_generator_current(rpm, generator)
            print(f"  gen{generator} rpm={rpm:.0f}: expected={expected:.6f}, actual={actual:.6f}")
            _assert_close(f"generator_{generator}_current", actual, expected)


def _validate_generator_switching() -> None:
    print("\nValidation 5 - generator switching logic:")
    sequences = [
        ("2390 rpm for 20 s", [(2390.0, 20.0)], False),
        ("2500 rpm for 7.9 s", [(2500.0, 7.9)], False),
        ("2500 rpm for 8.0 s", [(2500.0, 8.0)], True),
        ("2500 rpm, drop below threshold, then recover", [(2500.0, 5.0), (2300.0, 1.0), (2500.0, 3.0)], False),
        ("2500 rpm for >8 s", [(2500.0, 8.1)], True),
        ("2400 rpm for 8 s", [(2400.0, 8.0)], True),
    ]
    for label, steps, expected_latched in sequences:
        above_threshold_time_s = 0.0
        last_rpm = 0.0
        for rpm, dt_s in steps:
            above_threshold_time_s = update_generator_switch_timer(above_threshold_time_s, rpm, dt_s)
            last_rpm = rpm
        state = generator_switch_state(last_rpm, time_above_threshold_s=above_threshold_time_s)
        print(
            f"  {label}: rpm={last_rpm:.0f}, above_threshold_time={above_threshold_time_s:.1f}, "
            f"ready={state.ready}, latched={state.latched}, threshold={state.threshold_rpm:.0f}, hold={state.hold_time_s:.0f}"
        )
        if state.latched != expected_latched:
            raise AssertionError("generator switching logic did not match the documented rule")
        if not isclose(state.threshold_rpm, GENERATOR_SWITCH_THRESHOLD_RPM, rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError("generator switch threshold mismatch")
        if not isclose(state.hold_time_s, GENERATOR_SWITCH_HOLD_TIME_S, rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError("generator hold time mismatch")


def _validate_egt_spread_rule(states: list[HealthState]) -> None:
    print("\nValidation 6 - EGT spread rule:")
    low_branch = egt_spread_limit_from_fuel_flow(1.0)
    high_branch = egt_spread_limit_from_fuel_flow(10.0)
    print(f"  low-fuel branch limit = {low_branch:.1f} C")
    print(f"  high-fuel branch limit = {high_branch:.1f} C")
    _assert_close("low_branch", low_branch, EGT_SPREAD_LIMIT_LOW_LPH_C)
    _assert_close("high_branch", high_branch, EGT_SPREAD_LIMIT_HIGH_LPH_C)
    for state in states:
        fuel_lph_proxy = state.fuelflow_kgh / 0.75
        expected_limit = EGT_SPREAD_LIMIT_HIGH_LPH_C if fuel_lph_proxy > 3.0 else EGT_SPREAD_LIMIT_LOW_LPH_C
        print(
            f"  rpm={state.rpm:.0f}, throttle={state.throttle_pct:.1f}, fuel_flow_proxy_lph={fuel_lph_proxy:.2f}, "
            f"EGT_spread_C={state.EGT_spread_C:.2f}, limit={expected_limit:.1f}"
        )
        if state.EGT_spread_C > expected_limit + 1e-9:
            raise AssertionError("EGT spread exceeded the documented limit")


def _validate_provenance_and_production(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 7 - provenance and production authority:")
    known = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)
    health = get_health_state(known, time_above_threshold_s=10.0)
    if health.production_source != "calibrated_csv":
        raise AssertionError("Health layer must preserve CSV-authoritative production source")
    if health.provenance["generator_A_current_A"].label != "official_graph_digitized":
        raise AssertionError("Generator A provenance mismatch")
    if health.provenance["coolant_temp_C"].label != "tier2_proxy":
        raise AssertionError("Coolant provenance mismatch")
    if health.provenance["generator_switch_ready"].label != "official_procedure":
        raise AssertionError("Generator switch provenance mismatch")
    print(f"  production_source={health.production_source}")
    print(f"  generator_graph_condition_C={GENERATOR_GRAPH_CONDITION_C:.1f}")


def _validate_file_integrity(before: dict[str, str], after: dict[str, str]) -> None:
    print("\nValidation 8 - protected-file integrity:")
    if before != after:
        changed = sorted(set(before) ^ set(after))
        common = sorted(set(before) & set(after))
        modified = [path for path in common if before[path] != after[path]]
        raise AssertionError(f"protected file integrity failed: added/removed={changed}, modified={modified}")
    print(f"  protected files checked: {len(before)}")
    print("  no protected file hashes changed")


def _validate_py_compile() -> None:
    print("\nValidation 9 - compilation:")
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-m",
        "py_compile",
        str(ROOT / "engine_model" / "stage4_health_parameters.py"),
        str(ROOT / "engine_model" / "stage4_health_validation.py"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError("py_compile failed:\n" + (result.stdout or "") + (result.stderr or ""))
    print("  py_compile passed")


def main() -> int:
    print("=" * 94)
    print("STAGE 4 HEALTH PARAMETER VALIDATION")
    print("=" * 94)
    before = _snapshot_protected_files()
    model = Stage13HybridEngineOutput()

    _validate_known_csv_case(model)
    _validate_ambient_temperature_interface(model)
    health_states = _validate_health_states(model)
    _validate_throttle_response(model)
    _validate_generator_lookup()
    _validate_generator_switching()
    _validate_egt_spread_rule(health_states)
    _validate_provenance_and_production(model)
    _validate_py_compile()

    after = _snapshot_protected_files()
    _validate_file_integrity(before, after)

    print("\nStage 4 validation: PASS")
    print("Safe to proceed to Stage 5: yes, after review of this health layer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
