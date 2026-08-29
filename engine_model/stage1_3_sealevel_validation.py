"""
Stage 1.3: Sea-level baseline validation for the Rotax 915 iS reference deck.

This diagnostic reconstructs the baseline from the verified Stage 1.2
geometry and corrected valve timing, then runs a no-combustion gas-exchange
cycle against the exact CSV operating point:

- RPM = 3000
- altitude = 0 ft
- throttle = 56.5 %
- ambient temperature = 15 C
- power = 15.36454167 kW
- fuel flow = 6.02 kg/h
- plenum pressure = 0.6256 bar
- plenum temperature = 289.85 K

The script intentionally does not implement combustion. It only measures the
baseline gas-exchange work, trapped mass, and the resulting power/torque
deficit relative to the CSV target.
"""

from __future__ import annotations

from math import cos, pi, radians, sin
from pathlib import Path
import sys

import pandas as pd


CSV_PATH = Path(__file__).resolve().parents[1] / "rotax_915is_performance_map.csv"

ENGINE_CYLINDERS = 4
RPM = 3000.0
STEP_DEG = 1.0

ROTAX_GEOMETRY = {
    "cylinders": 4,
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "compression_ratio": 8.2,
}

# Verified Stage 1.2 valve timing, carried forward unchanged.
INTAKE_OPEN_DEG = 0.0
INTAKE_CLOSE_DEG = 228.0
EXHAUST_OPEN_DEG = 492.0
EXHAUST_CLOSE_DEG = 720.0

VALVE_COEFF_OPEN = 1.0e-3
VALVE_COEFF_CLOSED = 0.0

AIR_COMPOSITION = "O2:0.21, N2:0.79"
MECH = "gri30.yaml"

TARGET_CASE_FILTER = {
    "rpm": 3000,
    "alt_ft": 0,
    "throttle_pct": 56.5,
    "t_amb_C": 15,
}


def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


def is_valve_open(theta_deg: float, open_deg: float, close_deg: float) -> bool:
    theta = theta_deg % 720.0
    if close_deg > open_deg:
        return open_deg <= theta < close_deg
    if close_deg < open_deg:
        return theta >= open_deg or theta < close_deg
    return False


def load_target_row(csv_path: Path = CSV_PATH) -> dict:
    df = pd.read_csv(csv_path)
    mask = (
        (df["rpm"] == TARGET_CASE_FILTER["rpm"])
        & (df["alt_ft"] == TARGET_CASE_FILTER["alt_ft"])
        & (df["throttle_pct"] == TARGET_CASE_FILTER["throttle_pct"])
        & (df["t_amb_C"] == TARGET_CASE_FILTER["t_amb_C"])
    )
    rows = df.loc[mask].copy()
    if len(rows) != 1:
        raise ValueError(
            "Expected exactly one matching CSV row for the Stage 1.3 sea-level "
            f"case, found {len(rows)}."
        )
    return rows.iloc[0].to_dict()


def _create_solution(ct, mech: str = MECH):
    try:
        return ct.Solution(mech)
    except Exception:
        return ct.Solution("gri30")


def _set_thermo_state(gas, temperature_k: float, pressure_pa: float, composition: str):
    gas.TPX = temperature_k, pressure_pa, composition


def run_stage1_3_baseline(step_deg: float = STEP_DEG) -> dict:
    import cantera as ct

    row = load_target_row()

    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g["bore_m"], g["stroke_m"])
    Vc = clearance_volume_from_cr(Vd, g["compression_ratio"])
    V_tdc = cyl_volume_at_theta(Vd, Vc, 0.0)
    V_bdc = cyl_volume_at_theta(Vd, Vc, 180.0)
    piston_area = (pi / 4.0) * g["bore_m"] ** 2

    print("=" * 90)
    print("STAGE 1.3 BASELINE VALIDATION - NO COMBUSTION")
    print(f"Cantera version: {ct.__version__}")
    print("=" * 90)
    print("Selected CSV row:")
    print(
        "  case_no={case_no}, rpm={rpm}, p_amb_bar={p_amb_bar}, t_amb_C={t_amb_C}, "
        "throttle_pct={throttle_pct}, alt_ft={alt_ft}, power_kW={power_kW}, "
        "fuelflow_kgh={fuelflow_kgh}, p_plenum_bar={p_plenum_bar}, "
        "t_plenum_K={t_plenum_K}".format(**row)
    )

    print("\nVerified engine geometry:")
    print(f"  bore = {g['bore_m'] * 1000.0:.3f} mm")
    print(f"  stroke = {g['stroke_m'] * 1000.0:.3f} mm")
    print(f"  CR = {g['compression_ratio']:.3f}")
    print(f"  Vd = {Vd * 1e6:.3f} cc")
    print(f"  Vc = {Vc * 1e6:.3f} cc")
    print(f"  V(TDC) = {V_tdc * 1e6:.3f} cc")
    print(f"  V(BDC) = {V_bdc * 1e6:.3f} cc")

    print("\nCorrected Stage 1.2 valve timing carried forward:")
    print(f"  intake = {INTAKE_OPEN_DEG:.1f} -> {INTAKE_CLOSE_DEG:.1f} deg")
    print(f"  exhaust = {EXHAUST_OPEN_DEG:.1f} -> {EXHAUST_CLOSE_DEG:.1f} deg")
    overlap = [
        th
        for th in range(720)
        if is_valve_open(th, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)
        and is_valve_open(th, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)
    ]
    print(f"  overlap = {len(overlap)} deg")

    try:
        gas_cyl = _create_solution(ct)
        _set_thermo_state(gas_cyl, row["t_amb_C"] + 273.15, row["p_amb_bar"] * 1e5, AIR_COMPOSITION)
        cylinder = ct.IdealGasReactor(gas_cyl, clone=False)
    except TypeError:
        cylinder = ct.IdealGasReactor(gas_cyl)

    cylinder.volume = V_tdc
    cylinder.chemistry_enabled = False

    gas_remote = _create_solution(ct)
    _set_thermo_state(gas_remote, row["t_amb_C"] + 273.15, row["p_amb_bar"] * 1e5, AIR_COMPOSITION)
    try:
        remote = ct.IdealGasReactor(gas_remote, clone=False)
    except TypeError:
        remote = ct.IdealGasReactor(gas_remote)
    remote.volume = 1.0
    remote.chemistry_enabled = False

    piston = ct.Wall(cylinder, remote)
    piston.area = piston_area

    gas_inlet = _create_solution(ct)
    _set_thermo_state(gas_inlet, row["t_plenum_K"], row["p_plenum_bar"] * 1e5, AIR_COMPOSITION)
    try:
        inlet_res = ct.Reservoir(gas_inlet, clone=False)
    except TypeError:
        inlet_res = ct.Reservoir(gas_inlet)

    gas_outlet = _create_solution(ct)
    _set_thermo_state(gas_outlet, row["t_amb_C"] + 273.15, row["p_amb_bar"] * 1e5, AIR_COMPOSITION)
    try:
        outlet_res = ct.Reservoir(gas_outlet, clone=False)
    except TypeError:
        outlet_res = ct.Reservoir(gas_outlet)

    inlet_valve = ct.Valve(inlet_res, cylinder)
    outlet_valve = ct.Valve(cylinder, outlet_res)
    inlet_valve.valve_coeff = VALVE_COEFF_OPEN
    outlet_valve.valve_coeff = VALVE_COEFF_OPEN
    inlet_valve.time_function = lambda t: True
    outlet_valve.time_function = lambda t: True

    sim = ct.ReactorNet([cylinder, remote])
    sim.initialize()
    try:
        sim.max_time_step = (1.0 / (RPM * 360.0 / 60.0)) / 50.0
    except Exception:
        pass

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    total_steps = int(720.0 / step_deg)

    history = {
        "theta": [],
        "pressure": [],
        "temperature": [],
        "density": [],
        "mass": [],
        "volume": [],
        "inlet_open": [],
        "outlet_open": [],
        "mdot_in": [],
        "mdot_out": [],
    }

    local_t = 0.0
    prev_v = V_tdc
    prev_p = cylinder.phase.P
    total_work_j = 0.0
    pumping_work_j = 0.0
    compression_work_j = 0.0
    expansion_work_j = 0.0
    inducted_mass_kg = 0.0
    exhausted_mass_kg = 0.0

    p_at_ivc = None
    t_at_ivc = None
    m_at_ivc = None
    p_at_tdc = None
    t_at_tdc = None
    m_at_tdc = None

    for s in range(1, total_steps + 1):
        theta = s * step_deg
        v_new = cyl_volume_at_theta(Vd, Vc, theta)
        dV = v_new - prev_v
        dt = step_deg * sec_per_deg
        theta_mid = (theta - 0.5 * step_deg) % 720.0

        cylinder.volume = v_new
        piston.velocity = (dV / dt) / piston_area

        in_open = is_valve_open(theta, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)
        out_open = is_valve_open(theta, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)
        inlet_valve.valve_coeff = VALVE_COEFF_OPEN if in_open else VALVE_COEFF_CLOSED
        outlet_valve.valve_coeff = VALVE_COEFF_OPEN if out_open else VALVE_COEFF_CLOSED

        local_t += dt
        sim.advance(local_t)

        try:
            p_curr = cylinder.phase.P
            t_curr = cylinder.phase.T
            rho_curr = cylinder.phase.density
        except Exception:
            p_curr = cylinder.thermo.P
            t_curr = cylinder.thermo.T
            rho_curr = cylinder.thermo.density
        mass_curr = rho_curr * cylinder.volume

        dW = 0.5 * (prev_p + p_curr) * dV
        total_work_j += dW
        if theta_mid < INTAKE_CLOSE_DEG or theta_mid >= EXHAUST_OPEN_DEG:
            pumping_work_j += dW
        elif theta_mid < 360.0:
            compression_work_j += dW
        else:
            expansion_work_j += dW

        mdot_in = inlet_valve.mass_flow_rate
        mdot_out = outlet_valve.mass_flow_rate
        inducted_mass_kg += mdot_in * dt
        exhausted_mass_kg += mdot_out * dt

        history["theta"].append(theta)
        history["pressure"].append(p_curr)
        history["temperature"].append(t_curr)
        history["density"].append(rho_curr)
        history["mass"].append(mass_curr)
        history["volume"].append(v_new)
        history["inlet_open"].append(in_open)
        history["outlet_open"].append(out_open)
        history["mdot_in"].append(mdot_in)
        history["mdot_out"].append(mdot_out)

        if abs(theta - INTAKE_CLOSE_DEG) < 1e-9:
            p_at_ivc = p_curr
            t_at_ivc = t_curr
            m_at_ivc = mass_curr
        if abs(theta - 360.0) < 1e-9:
            p_at_tdc = p_curr
            t_at_tdc = t_curr
            m_at_tdc = mass_curr

        prev_v = v_new
        prev_p = p_curr

    single_cyl_work_j = total_work_j
    engine_work_j = single_cyl_work_j * ENGINE_CYLINDERS
    engine_power_w = engine_work_j * RPM / 120.0
    engine_torque_nm = engine_work_j / (4.0 * pi)
    single_cyl_power_w = single_cyl_work_j * RPM / 120.0
    single_cyl_torque_nm = single_cyl_work_j / (4.0 * pi)

    target_power_kw = float(row["power_kW"])
    target_power_w = target_power_kw * 1000.0
    target_torque_nm = target_power_w / (2.0 * pi * (RPM / 60.0))
    target_work_per_cyl_j = target_power_w * 120.0 / (RPM * ENGINE_CYLINDERS)
    target_work_per_engine_cycle_j = target_work_per_cyl_j * ENGINE_CYLINDERS
    target_fuel_flow_kg_s = float(row["fuelflow_kgh"]) / 3600.0
    fuel_mass_per_cyl_per_cycle = target_fuel_flow_kg_s / ENGINE_CYLINDERS / (RPM / 120.0)

    result = {
        "row": row,
        "geometry": g,
        "Vd_m3": Vd,
        "Vc_m3": Vc,
        "V_tdc_m3": V_tdc,
        "V_bdc_m3": V_bdc,
        "history": history,
        "single_cyl_work_J": single_cyl_work_j,
        "single_cyl_power_W": single_cyl_power_w,
        "single_cyl_torque_Nm": single_cyl_torque_nm,
        "engine_work_J": engine_work_j,
        "engine_power_W": engine_power_w,
        "engine_torque_Nm": engine_torque_nm,
        "pumping_work_J": pumping_work_j,
        "compression_work_J": compression_work_j,
        "expansion_work_J": expansion_work_j,
        "inducted_mass_kg": inducted_mass_kg,
        "exhausted_mass_kg": exhausted_mass_kg,
        "m_at_ivc_kg": m_at_ivc,
        "p_at_ivc_Pa": p_at_ivc,
        "t_at_ivc_K": t_at_ivc,
        "m_at_tdc_kg": m_at_tdc,
        "p_at_tdc_Pa": p_at_tdc,
        "t_at_tdc_K": t_at_tdc,
        "target_power_kw": target_power_kw,
        "target_power_w": target_power_w,
        "target_torque_nm": target_torque_nm,
        "target_work_per_cyl_j": target_work_per_cyl_j,
        "target_work_per_engine_cycle_j": target_work_per_engine_cycle_j,
        "target_fuel_flow_kg_s": target_fuel_flow_kg_s,
        "fuel_mass_per_cyl_per_cycle_kg": fuel_mass_per_cyl_per_cycle,
    }
    return result


def print_baseline_summary(result: dict) -> None:
    row = result["row"]
    target_power_kw = result["target_power_kw"]
    engine_power_kw = result["engine_power_W"] / 1000.0
    engine_torque_nm = result["engine_torque_Nm"]
    target_torque_nm = result["target_torque_nm"]

    print("\nNo-combustion baseline results:")
    print(f"  inducted_mass = {result['inducted_mass_kg'] * 1e3:.6f} g")
    print(f"  trapped_mass_at_ivc = {result['m_at_ivc_kg'] * 1e3:.6f} g")
    print(f"  p_at_ivc = {result['p_at_ivc_Pa'] / 1e5:.6f} bar")
    print(f"  p_at_tdc = {result['p_at_tdc_Pa'] / 1e5:.6f} bar")
    print(f"  pumping_work = {result['pumping_work_J']:.6f} J/cycle/cyl")
    print(f"  compression_work = {result['compression_work_J']:.6f} J/cycle/cyl")
    print(f"  expansion_work = {result['expansion_work_J']:.6f} J/cycle/cyl")
    print(f"  net_work = {result['single_cyl_work_J']:.6f} J/cycle/cyl")
    print(f"  predicted_engine_power = {engine_power_kw:.6f} kW")
    print(f"  predicted_engine_torque = {engine_torque_nm:.6f} N-m")

    power_err_pct = abs(engine_power_kw - target_power_kw) / target_power_kw * 100.0
    torque_err_pct = abs(engine_torque_nm - target_torque_nm) / target_torque_nm * 100.0

    print("\nTarget comparison:")
    print(f"  target_power = {target_power_kw:.8f} kW")
    print(f"  target_torque = {target_torque_nm:.8f} N-m")
    print(f"  power_error_pct = {power_err_pct:.6f} %")
    print(f"  torque_error_pct = {torque_err_pct:.6f} %")
    print(f"  work_per_cyl_target = {result['target_work_per_cyl_j']:.6f} J/cycle/cyl")
    print(f"  work_per_engine_cycle_target = {result['target_work_per_engine_cycle_j']:.6f} J/cycle/engine")

    print("\nExact CSV row used:")
    print(
        "  case_no={case_no}, rpm={rpm}, p_amb_bar={p_amb_bar}, t_amb_C={t_amb_C}, "
        "throttle_pct={throttle_pct}, alt_ft={alt_ft}, power_kW={power_kW}, "
        "fuelflow_kgh={fuelflow_kgh}, p_plenum_bar={p_plenum_bar}, "
        "t_plenum_K={t_plenum_K}".format(**row)
    )

    if result["m_at_ivc_kg"] is not None:
        print(f"  trapped_mass_exact = {result['m_at_ivc_kg']:.10e} kg")

    print("\nStage 1.3 baseline status: NO COMBUSTION, no fuel metering, no tuning.")


def main() -> int:
    result = run_stage1_3_baseline()
    print_baseline_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
