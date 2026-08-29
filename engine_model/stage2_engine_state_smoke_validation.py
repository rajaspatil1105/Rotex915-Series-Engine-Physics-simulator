"""
Stage 2 validation for the current simplified engine-state interface.

Validation only:
- reuses get_engine_state() from the existing Stage 1.3 hybrid layer
- does not modify the production model
- does not add turbo or injector physics
- does not reopen fired-cycle Cantera work
"""

from __future__ import annotations

import hashlib
from math import isfinite, isclose, pi
from pathlib import Path

import pandas as pd

from stage1_3_hybrid_engine_output import (
    CSV_PATH,
    Stage13HybridEngineOutput,
    fuel_mass_mg_per_cylinder_cycle_from_fuelflow,
    get_engine_state,
    torque_nm_from_power_kw,
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


def _assert_close(
    name: str,
    actual: float,
    expected: float,
    *,
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-9,
) -> None:
    if not isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol):
        raise AssertionError(f"{name} mismatch: actual={actual}, expected={expected}")


def _safe_float(value: float | int | None) -> float:
    if value is None:
        raise AssertionError("unexpected None value")
    value = float(value)
    if not isfinite(value):
        raise AssertionError(f"non-finite value: {value}")
    return value


def _print_state(prefix: str, state) -> None:
    print(
        f"{prefix}: rpm={state.rpm:.1f}, throttle={state.throttle_pct:.1f}, alt_ft={state.altitude_ft:.1f}, "
        f"t_amb_C={state.ambient_temp_C:.2f}, power_kW={state.power_kW:.6f}, torque_Nm={state.torque_Nm:.6f}, "
        f"fuelflow_kgh={state.fuelflow_kgh:.6f}, p_plenum_bar={state.p_plenum_bar:.4f}, "
        f"t_plenum_K={state.t_plenum_K:.2f}, fuel_mass_mg_per_cylinder_cycle={state.fuel_mass_mg_per_cylinder_cycle:.6f}, "
        f"ambient_source={state.ambient_source}, source={state.production_source}, physics={state.physics_source}, "
        f"status={state.validation_status}, exact={state.exact}, interpolated={state.interpolated}, "
        f"extrapolated={state.extrapolated}"
    )


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


def _compare_states_to_row(state, row: pd.Series) -> None:
    expected_power = float(row["power_kW"])
    expected_rpm = float(row["rpm"])
    expected_torque = torque_nm_from_power_kw(expected_power, expected_rpm)

    _assert_close("power_kW", state.power_kW, expected_power)
    _assert_close("torque_Nm", state.torque_Nm, expected_torque)
    _assert_close("fuelflow_kgh", state.fuelflow_kgh, float(row["fuelflow_kgh"]))
    _assert_close("p_plenum_bar", state.p_plenum_bar, float(row["p_plenum_bar"]))
    _assert_close("t_plenum_K", state.t_plenum_K, float(row["t_plenum_K"]))
    _assert_close(
        "fuel_mass_mg_per_cylinder_cycle",
        state.fuel_mass_mg_per_cylinder_cycle,
        fuel_mass_mg_per_cylinder_cycle_from_fuelflow(state.fuelflow_kgh, state.rpm),
    )
    _assert_close(
        "torque_from_power",
        state.torque_Nm,
        torque_nm_from_power_kw(state.power_kW, state.rpm),
    )


def _validate_state_sanity(state) -> None:
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
        "fuel_mass_mg_per_cylinder_cycle",
    ]:
        _safe_float(getattr(state, name))
    if state.power_kW <= 0.0:
        raise AssertionError("power_kW must be positive for positive-output operating points")
    if state.torque_Nm <= 0.0:
        raise AssertionError("torque_Nm must be positive for positive-output operating points")
    if state.fuelflow_kgh < 0.0:
        raise AssertionError("fuelflow_kgh must be non-negative")
    if state.p_plenum_bar <= 0.0:
        raise AssertionError("p_plenum_bar must be positive")
    if state.t_plenum_K <= 0.0:
        raise AssertionError("t_plenum_K must be positive")
    if state.production_source != "calibrated_csv":
        raise AssertionError("production source must remain calibrated_csv")
    if state.physics_source != "cantera_physics_derived":
        raise AssertionError("physics source must remain cantera_physics_derived")
    if state.validation_status not in {"validated_csv", "experimental_unvalidated"}:
        raise AssertionError("unexpected validation status")


def _validate_exact_csv_reproduction(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 1 - exact CSV reproduction:")
    case_nos = [2151, 161, 171, 181, 191]
    for case_no in case_nos:
        row = model.df.loc[model.df["case_no"] == case_no]
        if len(row) != 1:
            raise AssertionError(f"expected exactly one CSV row for case_no={case_no}")
        row = row.iloc[0]
        state = get_engine_state(
            float(row["rpm"]),
            float(row["throttle_pct"]),
            float(row["alt_ft"]),
            float(row["t_amb_C"]),
        )
        _print_state(f"  case_{case_no}", state)
        _compare_states_to_row(state, row)
        _validate_state_sanity(state)
        for field in ["power_kW", "torque_Nm", "fuelflow_kgh", "p_plenum_bar", "t_plenum_K"]:
            actual = float(getattr(state, field))
            expected = float(
                row[field]
                if field != "torque_Nm"
                else torque_nm_from_power_kw(float(row["power_kW"]), float(row["rpm"]))
            )
            abs_err = abs(actual - expected)
            rel_err = abs_err / abs(expected) if expected != 0.0 else abs_err
            print(f"    {field}: abs_err={abs_err:.12e}, rel_err={rel_err:.12e}")


def _validate_power_torque_consistency(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 2 - power/torque consistency:")
    points = [
        (2151, 3000.0, 56.5, 0.0, 15.0),
        (161, 5800.0, 100.0, 0.0, 15.0),
        (171, 5800.0, 99.4, 0.0, 15.0),
        (181, 5800.0, 98.8, 0.0, 15.0),
        (191, 5800.0, 97.4, 0.0, 15.0),
    ]
    for case_no, rpm, throttle, alt, tamb in points:
        state = get_engine_state(rpm, throttle, alt, tamb)
        expected = torque_nm_from_power_kw(state.power_kW, rpm)
        abs_err = abs(state.torque_Nm - expected)
        rel_err = abs_err / abs(expected) if expected != 0.0 else abs_err
        print(
            f"  case_{case_no}: expected_torque={expected:.12f}, returned_torque={state.torque_Nm:.12f}, "
            f"abs_err={abs_err:.12e}, rel_err={rel_err:.12e}"
        )
        _assert_close("torque_consistency", state.torque_Nm, expected, rel_tol=1e-12, abs_tol=1e-12)


def _validate_interpolation(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 3 - interpolation and continuity:")
    interpolation_points = [
        ("rpm_midpoint", 3250.0, 56.5, 0.0, None),
        ("throttle_midpoint", 3000.0, 64.0, 0.0, None),
        ("altitude_midpoint", 3000.0, 56.5, 1500.0, None),
        ("combined_interior", 4300.0, 78.25, 8000.0, None),
    ]
    for name, rpm, throttle, alt, tamb in interpolation_points:
        state = get_engine_state(rpm, throttle, alt, tamb)
        _print_state(f"  {name}", state)
        _validate_state_sanity(state)
        if state.exact:
            raise AssertionError(f"{name} unexpectedly matched an exact CSV row")

    center = get_engine_state(4300.0, 78.25, 8000.0)
    neighbors = [
        get_engine_state(4300.25, 78.27, 8001.0),
        get_engine_state(4299.75, 78.23, 7999.0),
    ]
    print("  continuity_probe:")
    _print_state("    center", center)
    for idx, neighbor in enumerate(neighbors, start=1):
        _print_state(f"    neighbor_{idx}", neighbor)
        _validate_state_sanity(neighbor)
        for field in ["power_kW", "torque_Nm", "fuelflow_kgh", "p_plenum_bar", "t_plenum_K"]:
            c = float(getattr(center, field))
            n = float(getattr(neighbor, field))
            delta = abs(n - c)
            rel = delta / abs(c) if c != 0.0 else delta
            print(f"      {field}: abs_delta={delta:.12e}, rel_delta={rel:.12e}")
            if rel > 0.01:
                raise AssertionError(f"{field} changed too sharply for a tiny interpolation perturbation")


def _validate_throttle_response(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 4 - throttle response:")
    rows = model.df.loc[
        (model.df["rpm"] == 3000) & (model.df["alt_ft"] == 0) & (model.df["t_amb_C"] == 15)
    ].sort_values("throttle_pct")
    throttle_set = [56.5, 72.0, 84.5, 94.1, 100.0]
    rows = rows.loc[rows["throttle_pct"].isin(throttle_set)].sort_values("throttle_pct")
    if len(rows) != len(throttle_set):
        raise AssertionError("missing expected throttle levels at 3000 rpm, 0 ft, 15 C")

    previous = None
    for _, row in rows.iterrows():
        state = get_engine_state(float(row["rpm"]), float(row["throttle_pct"]), float(row["alt_ft"]), float(row["t_amb_C"]))
        _print_state(f"  throttle_{float(row['throttle_pct']):.1f}", state)
        _compare_states_to_row(state, row)
        _validate_state_sanity(state)
        if previous is not None:
            for field in ["power_kW", "torque_Nm", "fuelflow_kgh", "p_plenum_bar"]:
                now = float(getattr(state, field))
                prev = float(getattr(previous, field))
                if now + 1e-9 < prev:
                    print(
                        f"    source reversal observed in {field}: "
                        f"{prev:.6f} -> {now:.6f} between throttles {previous.throttle_pct:.1f} and {state.throttle_pct:.1f}"
                    )
        previous = state


def _validate_boost_sanity(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 5 - boost/plenum sanity:")
    boosted_rows = model.df.loc[
        (model.df["rpm"] == 5800) & (model.df["throttle_pct"] == 100.0)
    ].sort_values("alt_ft").head(5)
    for _, row in boosted_rows.iterrows():
        state = get_engine_state(float(row["rpm"]), float(row["throttle_pct"]), float(row["alt_ft"]), float(row["t_amb_C"]))
        _print_state(f"  boost_case_{int(row['case_no'])}", state)
        _compare_states_to_row(state, row)
        _validate_state_sanity(state)
        p_amb = float(row["p_amb_bar"])
        if not (state.p_plenum_bar > 0.0 and p_amb > 0.0):
            raise AssertionError("ambient or plenum pressure not positive")
        if state.p_plenum_bar <= p_amb:
            raise AssertionError("boosted plenum pressure should exceed ambient pressure for these valid points")
        print(f"    ambient_pressure_bar={p_amb:.6f}, plenum_minus_ambient_bar={state.p_plenum_bar - p_amb:.6f}")


def _validate_output_sanity(model: Stage13HybridEngineOutput) -> None:
    print("\nValidation 6 - output sanity:")
    validation_points = [
        (2151, 3000.0, 56.5, 0.0, 15.0),
        (161, 5800.0, 100.0, 0.0, 15.0),
        (171, 5800.0, 99.4, 0.0, 15.0),
        (3250.0, 64.0, 1500.0, None, None),
        (4300.0, 78.25, 8000.0, None, None),
    ]
    for item in validation_points:
        if len(item) == 5 and item[3] is not None:
            case_no, rpm, throttle, alt, tamb = item
            state = get_engine_state(rpm, throttle, alt, tamb)
            label = f"case_{case_no}"
        else:
            rpm, throttle, alt, tamb, _ = item
            state = get_engine_state(rpm, throttle, alt)
            label = f"interp_{rpm:.0f}_{throttle:.2f}_{alt:.0f}"
        _print_state(f"  {label}", state)
        _validate_state_sanity(state)


def _validate_out_of_envelope() -> None:
    print("\nValidation 7 - out-of-envelope protection:")
    try:
        get_engine_state(2500.0, 56.5, 0.0)
    except ValueError as exc:
        print(f"  rejected as expected: {exc}")
    else:
        raise AssertionError("out-of-envelope input was not rejected")


def _validate_provenance() -> None:
    print("\nValidation 8 - source/provenance:")
    state = get_engine_state(3000.0, 56.5, 0.0, 15.0)
    print(
        f"  production_source={state.production_source}, physics_source={state.physics_source}, "
        f"validation_status={state.validation_status}"
    )
    if state.production_source != "calibrated_csv":
        raise AssertionError("production outputs must remain CSV-authoritative")
    if state.physics_source != "cantera_physics_derived":
        raise AssertionError("physics source must remain cantera_physics_derived")
    if "cantera" in state.production_source.lower():
        raise AssertionError("production source must not be Cantera")


def _validate_file_integrity(before: dict[str, str], after: dict[str, str]) -> None:
    print("\nValidation 9 - protected-file integrity:")
    if before != after:
        changed = sorted(set(before) ^ set(after))
        common = sorted(set(before) & set(after))
        modified = [path for path in common if before[path] != after[path]]
        raise AssertionError(
            "protected file integrity failed: "
            f"added/removed={changed}, modified={modified}"
        )
    print(f"  protected files checked: {len(before)}")
    print("  no protected file hashes changed")


def _validate_py_compile() -> None:
    print("\nValidation 10 - compilation:")
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-m",
        "py_compile",
        str(ROOT / "engine_model" / "stage1_3_hybrid_engine_output.py"),
        str(ROOT / "engine_model" / "stage2_engine_state_smoke_validation.py"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            "py_compile failed:\n"
            + (result.stdout or "")
            + (result.stderr or "")
        )
    print("  py_compile passed")


def main() -> int:
    print("=" * 94)
    print("STAGE 2 FULL VALIDATION")
    print("=" * 94)
    if not callable(get_engine_state):
        raise AssertionError("get_engine_state() is not available")
    if not hasattr(Stage13HybridEngineOutput, "get_engine_state"):
        raise AssertionError("Stage13HybridEngineOutput.get_engine_state() is missing")

    before_hashes = _snapshot_protected_files()
    model = Stage13HybridEngineOutput()

    print(f"CSV path: {CSV_PATH}")
    print(f"Rows: {len(model.df)}")

    _validate_exact_csv_reproduction(model)
    _validate_power_torque_consistency(model)
    _validate_interpolation(model)
    _validate_throttle_response(model)
    _validate_boost_sanity(model)
    _validate_output_sanity(model)
    _validate_out_of_envelope()
    _validate_provenance()
    _validate_py_compile()

    after_hashes = _snapshot_protected_files()
    _validate_file_integrity(before_hashes, after_hashes)

    print("\nOverall Stage 2 validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
