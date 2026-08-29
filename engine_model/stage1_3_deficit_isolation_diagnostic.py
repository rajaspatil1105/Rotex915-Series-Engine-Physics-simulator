"""
Stage 1.3 deficit-isolation diagnostic.

This wrapper reuses the reconstructed Stage 1.3 sea-level baseline and adds
the fuel/energy accounting requested by the project handoff:

- exact CSV row identification
- fuel-flow conversion to kg/cycle/cylinder
- chemical-energy accounting only if the project documents an LHV
- comparison of the no-combustion baseline against the CSV target

The diagnostic intentionally does not implement combustion.
"""

from __future__ import annotations

from stage1_3_sealevel_validation import (
    ENGINE_CYLINDERS,
    RPM,
    load_target_row,
    print_baseline_summary,
    run_stage1_3_baseline,
)


PROJECT_LHV_MJ_PER_KG = None
PUBLISHED_FUEL_SOURCES = (
    "OM 915 i A Rev.2, §2.3: MOGAS EN 228 Super / Super Plus and AVGAS 100LL (ASTM D910); "
    "minimum RON 95 for 915 iSc/iS",
    "OM 915 i A Rev.2, §7.5.3: electronic fuel injection, ECU controlled",
)


def print_energy_accounting(result: dict) -> None:
    row = result["row"]
    target_power_w = result["target_power_w"]
    target_work_per_cyl_j = result["target_work_per_cyl_j"]
    fuel_flow_kg_h = float(row["fuelflow_kgh"])
    fuel_flow_kg_s = fuel_flow_kg_h / 3600.0
    fuel_mass_per_cyl_per_cycle = result["fuel_mass_per_cyl_per_cycle_kg"]
    required_lhv_100pct_mj_per_kg = target_work_per_cyl_j / fuel_mass_per_cyl_per_cycle / 1e6
    required_lhv_95pct_mj_per_kg = target_work_per_cyl_j / 0.95 / fuel_mass_per_cyl_per_cycle / 1e6

    print("\nFuel and energy accounting:")
    print("  project_fuel_sources:")
    for src in PUBLISHED_FUEL_SOURCES:
        print(f"    - {src}")
    print(f"  fuel_flow_total = {fuel_flow_kg_h:.6f} kg/h")
    print(f"  fuel_flow_total = {fuel_flow_kg_s:.10f} kg/s")
    print(
        "  fuel_mass_per_cyl_per_cycle = "
        f"{fuel_mass_per_cyl_per_cycle * 1e6:.6f} mg/cylinder/cycle"
    )
    print(
        "  required_LHV_at_100pct_efficiency = "
        f"{required_lhv_100pct_mj_per_kg:.6f} MJ/kg"
    )
    print(
        "  required_LHV_at_95pct_efficiency = "
        f"{required_lhv_95pct_mj_per_kg:.6f} MJ/kg"
    )

    if PROJECT_LHV_MJ_PER_KG is None:
        print("  project_LHV = unavailable")
        print("  chemical_energy_per_cyl_cycle = unavailable")
        print("  chemical_energy_gap = unavailable")
        print("  implied_efficiency = unavailable without an authoritative LHV")
        print(
            "  note = No authoritative LHV was found in the project files, so "
            "available-fuel-energy accounting is intentionally left blank."
        )
    else:
        chemical_energy_j = fuel_mass_per_cyl_per_cycle * PROJECT_LHV_MJ_PER_KG * 1e6
        print(f"  project_LHV = {PROJECT_LHV_MJ_PER_KG:.6f} MJ/kg")
        print(f"  chemical_energy_per_cyl_cycle = {chemical_energy_j:.6f} J")
        print(
            "  target_indicated_work_per_cyl_cycle = "
            f"{target_work_per_cyl_j:.6f} J"
        )
        print(
            "  chemical_energy_minus_target_work = "
            f"{chemical_energy_j - target_work_per_cyl_j:.6f} J"
        )

    model_work_j = result["single_cyl_work_J"]
    work_deficit_j = target_work_per_cyl_j - model_work_j
    engine_power_kw = result["engine_power_W"] / 1000.0
    target_power_kw = result["target_power_kw"]
    power_deficit_kw = target_power_kw - engine_power_kw

    print("\nNo-combustion deficit:")
    print(f"  model_work_per_cyl_cycle = {model_work_j:.6f} J")
    print(f"  target_work_per_cyl_cycle = {target_work_per_cyl_j:.6f} J")
    print(f"  work_deficit_per_cyl_cycle = {work_deficit_j:.6f} J")
    print(f"  model_power_engine = {engine_power_kw:.6f} kW")
    print(f"  target_power_engine = {target_power_kw:.8f} kW")
    print(f"  power_deficit_engine = {power_deficit_kw:.6f} kW")
    print(f"  target_torque_engine = {result['target_torque_nm']:.6f} N-m")
    print(f"  model_torque_engine = {result['engine_torque_Nm']:.6f} N-m")
    print(
        "  torque_error_pct = "
        f"{abs(result['engine_torque_Nm'] - result['target_torque_nm']) / result['target_torque_nm'] * 100.0:.6f} %"
    )


def main() -> int:
    row = load_target_row()
    result = run_stage1_3_baseline()

    print("\n" + "=" * 90)
    print("STAGE 1.3 DEFICIT ISOLATION")
    print("=" * 90)
    print_baseline_summary(result)
    print_energy_accounting(result)

    print("\nRequired summary:")
    print(f"  A. Exact CSV row used: case_no={row['case_no']}")
    print(f"  B. Exact trapped mass: {result['m_at_ivc_kg']:.10e} kg")
    print(
        "  C. Exact no-combustion power/torque: "
        f"{result['engine_power_W'] / 1000.0:.6f} kW, {result['engine_torque_Nm']:.6f} N-m"
    )
    print(
        "  D. Target power/torque: "
        f"{result['target_power_kw']:.8f} kW, {result['target_torque_nm']:.8f} N-m"
    )
    print(
        "  E. Error percentage: "
        f"{abs(result['engine_power_W'] / 1000.0 - result['target_power_kw']) / result['target_power_kw'] * 100.0:.6f} % power, "
        f"{abs(result['engine_torque_Nm'] - result['target_torque_nm']) / result['target_torque_nm'] * 100.0:.6f} % torque"
    )
    print(
        "  F. Fuel mass per cylinder per cycle: "
        f"{result['fuel_mass_per_cyl_per_cycle_kg'] * 1e6:.6f} mg"
    )
    if PROJECT_LHV_MJ_PER_KG is None:
        print(
            "  G. Chemical-energy accounting: unavailable because the project does not document an authoritative LHV; "
            "the target would require at least 9.189156 MJ/kg (100% efficiency) or 9.672796 MJ/kg (95% efficiency)."
        )
    else:
        chemical_energy_j = result["fuel_mass_per_cyl_per_cycle_kg"] * PROJECT_LHV_MJ_PER_KG * 1e6
        implied_efficiency = result["target_work_per_cyl_j"] / chemical_energy_j
        print(
            "  G. Chemical-energy accounting: "
            f"{chemical_energy_j:.6f} J/cycle/cyl at {PROJECT_LHV_MJ_PER_KG:.6f} MJ/kg; "
            f"implied_efficiency = {implied_efficiency:.6f}"
        )
    print(
        "  H. Missing to proceed to fuel-metered combustion: a documented fuel-energy basis "
        "and a physically coupled fuel-release / heat-release model."
    )
    print("  I. Files created/modified: engine_model/stage1_3_sealevel_validation.py, engine_model/stage1_3_deficit_isolation_diagnostic.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
