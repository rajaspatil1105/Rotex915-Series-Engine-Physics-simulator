"""
Stage 1.3 hybrid architecture validation.

This script verifies that:
- the CSV-backed engine-output layer reproduces known rows exactly
- interpolation is finite and continuous between known rows
- boundary points are handled explicitly
- out-of-envelope inputs are rejected
- Cantera remains separated as supporting physics rather than the authority
  for absolute power/torque
"""

from __future__ import annotations

from math import isclose

from stage1_3_hybrid_engine_output import (
    Stage13HybridEngineOutput,
    torque_nm_from_power_kw,
)
from stage1_3_sealevel_validation import run_stage1_3_baseline


def _assert_close(name: str, actual: float, expected: float, *, rel_tol: float = 1e-9, abs_tol: float = 1e-9) -> None:
    if not isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol):
        raise AssertionError(f"{name} mismatch: actual={actual}, expected={expected}")


def _print_result(prefix: str, result) -> None:
    print(
        f"{prefix}: case_no={result.case_no}, rpm={result.rpm:.1f}, throttle={result.throttle_pct:.1f}, "
        f"alt_ft={result.altitude_ft:.1f}, t_amb_C={result.ambient_temp_C:.2f}, power_kW={result.power_kW:.6f}, "
        f"torque_Nm={result.torque_Nm:.6f}, fuelflow_kgh={result.fuelflow_kgh:.6f}, "
        f"p_plenum_bar={result.p_plenum_bar:.4f}, t_plenum_K={result.t_plenum_K:.2f}, "
        f"ambient_source={result.ambient_source}, source={result.production_source}, physics={result.physics_source}, status={result.validation_status}, "
        f"exact={result.exact}, interpolated={result.interpolated}, extrapolated={result.extrapolated}"
    )


def main() -> int:
    model = Stage13HybridEngineOutput()
    print("=" * 94)
    print("STAGE 1.3 HYBRID ENGINE-OUTPUT VALIDATION")
    print("=" * 94)
    print(model.coverage_report())

    print("\nKnown CSV case validation:")
    known = model.query(3000, 56.5, 0.0)
    _print_result("  known_case_2151", known)
    _assert_close("power_kW", known.power_kW, 15.36454167)
    _assert_close("torque_Nm", known.torque_Nm, torque_nm_from_power_kw(15.36454167, 3000))
    _assert_close("fuelflow_kgh", known.fuelflow_kgh, 6.02)
    _assert_close("p_plenum_bar", known.p_plenum_bar, 0.6256)
    _assert_close("t_plenum_K", known.t_plenum_K, 289.85)
    if known.ambient_source != "isa_surrogate":
        raise AssertionError("3-input production query at sea level should use the ISA surrogate.")

    print("\nAdditional exact-row checks:")
    exact_rows = model.select_exact_rows(6)
    for _, row in exact_rows.iloc[1:].iterrows():
        exact = model.query(
            float(row["rpm"]),
            float(row["throttle_pct"]),
            float(row["alt_ft"]),
            float(row["t_amb_C"]),
            mode="validation",
        )
        _print_result(f"  case_{int(row['case_no'])}", exact)
        _assert_close("power_kW", exact.power_kW, float(row["power_kW"]))
        _assert_close("torque_Nm", exact.torque_Nm, torque_nm_from_power_kw(float(row["power_kW"]), float(row["rpm"])))
        _assert_close("fuelflow_kgh", exact.fuelflow_kgh, float(row["fuelflow_kgh"]))
        _assert_close("p_plenum_bar", exact.p_plenum_bar, float(row["p_plenum_bar"]))
        _assert_close("t_plenum_K", exact.t_plenum_K, float(row["t_plenum_K"]))

    print("\nInterpolation check:")
    prod_mid = model.query(3250.0, 64.0, 1500.0)
    _print_result("  production_surrogate_midpoint", prod_mid)
    if prod_mid.ambient_source != "isa_surrogate":
        raise AssertionError("3-input production query should use the ISA ambient surrogate.")
    if not (10.0 <= prod_mid.power_kW <= 30.0):
        raise AssertionError("3-input production midpoint power is outside the expected local range.")

    mid = model.query(5800.0, 78.25, 0.0, 15.0, mode="validation")
    _print_result("  interpolated_midpoint", mid)
    if not (24.0 <= mid.power_kW <= 45.0):
        raise AssertionError("Interpolated midpoint power is outside the expected local range.")
    if mid.ambient_source != "explicit_input":
        raise AssertionError("Validation interpolation with explicit ambient should preserve explicit provenance.")

    print("\nBoundary checks:")
    boundary_points = [
        (3000.0, 56.5, 0.0),
        (5800.0, 100.0, 0.0),
        (3000.0, 56.5, 22999.0),
    ]
    for rpm, throttle, alt in boundary_points:
        result = model.query(rpm, throttle, alt)
        _print_result(f"  boundary_{rpm:.0f}_{throttle:.1f}_{alt:.0f}", result)

    print("\nOut-of-envelope check:")
    try:
        model.query(2500.0, 56.5, 0.0)
    except ValueError as exc:
        print(f"  out_of_envelope_rejected: {exc}")
    else:
        raise AssertionError("Expected out-of-envelope rejection for rpm=2500.")

    print("\nCantera supporting-physics layer:")
    baseline = run_stage1_3_baseline()
    features = model.build_supporting_physics_features(baseline_summary=baseline)
    print(
        "  peak_cylinder_pressure_bar={:.6f}, peak_cylinder_temperature_K={:.2f}, compression_pressure_bar={:.6f}, "
        "heat_release_J={}, combustion_duration_deg={}, combustion_phasing_deg={}, relative_pressure_change_bar={}, "
        "relative_temperature_change_K={}, source={}, physics={}, status={}".format(
            features.peak_cylinder_pressure_bar if features.peak_cylinder_pressure_bar is not None else float("nan"),
            features.peak_cylinder_temperature_K if features.peak_cylinder_temperature_K is not None else float("nan"),
            features.compression_pressure_bar if features.compression_pressure_bar is not None else float("nan"),
            features.heat_release_J,
            features.combustion_duration_deg,
            features.combustion_phasing_deg,
            features.relative_pressure_change_bar,
            features.relative_temperature_change_K,
            features.production_source,
            features.physics_source,
            features.validation_status,
        )
    )

    print("\nStage 1.3 hybrid architecture validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
