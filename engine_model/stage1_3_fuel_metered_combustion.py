"""
Stage 1.3 fuel-metered combustion diagnostic.

This script extends the reconstructed Stage 1.3 baseline with an explicit,
fuel-mass-driven heat-release model. It preserves the verified Stage 1.2
geometry, corrected valve timing, and Wall-driven piston while keeping the
fuel-energy accounting explicit.

The combustion source is deliberately smooth:
- The heat-release envelope is widened around the existing nominal ignition
  center near 700 deg CA.
- Heat release is mapped with a C1-continuous 5th-order smoothstep profile.
- The wall motion and heat release are provided to Cantera as time functions,
  so the source terms are continuous instead of piecewise-constant updates.

Important:
- The project does not provide an authoritative LHV.
- This file therefore exposes LHV as an explicit external/model assumption.
- The default below is based on published Avgas 100LL net heat of combustion
  and should be replaced when the project selects a definitive fuel basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians, sin

from stage1_3_sealevel_validation import (
    AIR_COMPOSITION,
    ENGINE_CYLINDERS,
    EXHAUST_CLOSE_DEG,
    EXHAUST_OPEN_DEG,
    INTAKE_CLOSE_DEG,
    INTAKE_OPEN_DEG,
    RPM,
    STEP_DEG,
    TARGET_CASE_FILTER,
    VALVE_COEFF_CLOSED,
    VALVE_COEFF_OPEN,
    CSV_PATH,
    _create_solution,
    _set_thermo_state,
    clearance_volume_from_cr,
    cyl_volume_at_theta,
    is_valve_open,
    load_target_row,
    swept_volume_per_cylinder,
    ROTAX_GEOMETRY,
)


# External/model assumption only. Replace when an authoritative project fuel
# specification is selected.
FUEL_NAME = "AVGAS 100LL"
LHV_MJ_PER_KG = 43.50
LHV_SOURCE = (
    "External assumption based on published Avgas 100LL net heat of combustion; "
    "not stored in project calibration/CSV files."
)
LHV_STATUS = "EXTERNAL_MODEL_ASSUMPTION"

COMBUSTION_EFFICIENCY = 0.95

# Preserve the established Stage 1.2 ignition timing, but map it to the 720-deg
# convention used by the validated crank-angle sequence:
# 20 deg BTDC of compression TDC (360 deg) -> 340 deg CA.
IGNITION_BTDC_DEG = 20.0
IGNITION_CENTER_DEG = 360.0 - IGNITION_BTDC_DEG  # 340 deg CA
BURN_START_DEG = 320.0
BURN_END_DEG = 380.0

# Smooth, physically interpretable burn profile.
PROFILE_NAME = "5th_order_smootherstep"


@dataclass(frozen=True)
class CombustionConfig:
    lhv_mj_per_kg: float
    lhv_source: str
    lhv_status: str
    combustion_efficiency: float
    ignition_center_deg: float
    burn_start_deg: float
    burn_end_deg: float
    profile_name: str


def smootherstep_5(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def smootherstep_5_derivative(x: float) -> float:
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return 30.0 * x * x * (1.0 - x) * (1.0 - x)


def burn_fraction(theta_deg: float, start_deg: float, end_deg: float) -> float:
    if theta_deg <= start_deg:
        return 0.0
    if theta_deg >= end_deg:
        return 1.0
    x = (theta_deg - start_deg) / (end_deg - start_deg)
    return smootherstep_5(x)


def burn_fraction_rate_per_deg(theta_deg: float, start_deg: float, end_deg: float) -> float:
    if theta_deg <= start_deg or theta_deg >= end_deg:
        return 0.0
    x = (theta_deg - start_deg) / (end_deg - start_deg)
    return smootherstep_5_derivative(x) / (end_deg - start_deg)


def build_theta_schedule(
    theta_end_deg: float,
    coarse_step_deg: float = 1.0,
    dense_start_deg: float = BURN_START_DEG,
    dense_end_deg: float = BURN_END_DEG,
    dense_step_deg: float = 0.1,
) -> list[float]:
    """Generate a time-ordered crank-angle schedule with extra density near combustion."""

    theta_values: list[float] = []
    theta = 0.0
    while theta < min(dense_start_deg, theta_end_deg):
        theta_values.append(round(theta, 10))
        theta += coarse_step_deg

    if theta_values and theta_values[-1] != dense_start_deg and dense_start_deg <= theta_end_deg:
        theta_values.append(round(dense_start_deg, 10))
    elif not theta_values and dense_start_deg <= theta_end_deg:
        theta_values.append(round(dense_start_deg, 10))

    theta = max(dense_start_deg, theta_values[-1] if theta_values else 0.0)
    if theta < dense_start_deg:
        theta = dense_start_deg

    if dense_start_deg <= theta_end_deg:
        theta = dense_start_deg
        while theta < min(dense_end_deg, theta_end_deg):
            if not theta_values or abs(theta_values[-1] - theta) > 1e-12:
                theta_values.append(round(theta, 10))
            theta += dense_step_deg

    if theta_end_deg >= dense_end_deg:
        theta = dense_end_deg
        if not theta_values or abs(theta_values[-1] - theta) > 1e-12:
            theta_values.append(round(theta, 10))
        theta += coarse_step_deg
        while theta <= theta_end_deg + 1e-12:
            theta_values.append(round(min(theta, theta_end_deg), 10))
            theta += coarse_step_deg
    else:
        if not theta_values or abs(theta_values[-1] - theta_end_deg) > 1e-12:
            theta_values.append(round(theta_end_deg, 10))

    # Remove accidental duplicates while preserving order.
    deduped: list[float] = []
    for value in theta_values:
        if not deduped or abs(deduped[-1] - value) > 1e-12:
            deduped.append(value)
    return deduped


def _theta_from_time(t: float, deg_per_sec: float) -> float:
    return t * deg_per_sec


def _wall_velocity_m_per_s(t: float, deg_per_sec: float, vd: float, piston_area: float) -> float:
    theta_deg = _theta_from_time(t, deg_per_sec)
    theta_rad = radians(theta_deg % 720.0)
    dV_dtheta_deg = 0.5 * vd * sin(theta_rad) * (pi / 180.0)
    return (dV_dtheta_deg * deg_per_sec) / piston_area


def _heat_release_rate_w(
    t: float,
    deg_per_sec: float,
    total_heat_release_j: float,
    burn_start_deg: float,
    burn_end_deg: float,
) -> float:
    theta_deg = _theta_from_time(t, deg_per_sec)
    rate_per_deg = burn_fraction_rate_per_deg(theta_deg, burn_start_deg, burn_end_deg)
    return total_heat_release_j * rate_per_deg * deg_per_sec


def _burn_fraction_at_time(
    t: float,
    deg_per_sec: float,
    burn_start_deg: float,
    burn_end_deg: float,
) -> float:
    theta_deg = _theta_from_time(t, deg_per_sec)
    return burn_fraction(theta_deg, burn_start_deg, burn_end_deg)


def _build_case(row: dict, ct):
    g = ROTAX_GEOMETRY
    vd = swept_volume_per_cylinder(g["bore_m"], g["stroke_m"])
    vc = clearance_volume_from_cr(vd, g["compression_ratio"])
    v_tdc = cyl_volume_at_theta(vd, vc, 0.0)
    piston_area = (pi / 4.0) * g["bore_m"] ** 2

    try:
        gas_cyl = _create_solution(ct)
        _set_thermo_state(gas_cyl, row["t_amb_C"] + 273.15, row["p_amb_bar"] * 1e5, AIR_COMPOSITION)
        cylinder = ct.IdealGasReactor(gas_cyl, clone=False)
    except TypeError:
        cylinder = ct.IdealGasReactor(gas_cyl)

    cylinder.volume = v_tdc
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

    return {
        "geometry": g,
        "Vd": vd,
        "Vc": vc,
        "V_tdc": v_tdc,
        "piston_area": piston_area,
        "cylinder": cylinder,
        "remote": remote,
        "piston": piston,
        "inlet_valve": inlet_valve,
        "outlet_valve": outlet_valve,
    }


def _set_valves(theta_deg: float, inlet_valve, outlet_valve) -> tuple[bool, bool]:
    in_open = is_valve_open(theta_deg, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)
    out_open = is_valve_open(theta_deg, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)
    inlet_valve.valve_coeff = VALVE_COEFF_OPEN if in_open else VALVE_COEFF_CLOSED
    outlet_valve.valve_coeff = VALVE_COEFF_OPEN if out_open else VALVE_COEFF_CLOSED
    return in_open, out_open


def _prepare_simulation(ct, cylinder, remote, deg_per_sec: float):
    sim = ct.ReactorNet([cylinder, remote])
    sim.initialize()
    try:
        # Smaller internal steps around ignition help the solver stay on the smooth source.
        sim.max_time_step = min((1.0 / deg_per_sec) / 120.0, 5.0e-7)
    except Exception:
        pass
    return sim


def _advance_case(
    *,
    ct,
    row: dict,
    config: CombustionConfig,
    theta_targets: list[float],
    log_window: tuple[float, float] | None,
    case_label: str,
    detailed_window: bool,
) -> dict:
    g = ROTAX_GEOMETRY
    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec

    Vd = swept_volume_per_cylinder(g["bore_m"], g["stroke_m"])
    Vc = clearance_volume_from_cr(Vd, g["compression_ratio"])
    V_tdc = cyl_volume_at_theta(Vd, Vc, 0.0)
    piston_area = (pi / 4.0) * g["bore_m"] ** 2

    total_heat_release_j = (
        (float(row["fuelflow_kgh"]) / 3600.0)
        / ENGINE_CYLINDERS
        / (RPM / 120.0)
        * config.lhv_mj_per_kg
        * 1e6
        * config.combustion_efficiency
    )

    system = _build_case(row, ct)
    cylinder = system["cylinder"]
    remote = system["remote"]
    piston = system["piston"]
    inlet_valve = system["inlet_valve"]
    outlet_valve = system["outlet_valve"]

    wall_velocity_fn = ct.Func1(
        lambda t, dp=deg_per_sec, vd=Vd, pa=piston_area: _wall_velocity_m_per_s(t, dp, vd, pa)
    )
    wall_heat_flux_fn = ct.Func1(
        lambda t,
        dp=deg_per_sec,
        q=total_heat_release_j,
        start=config.burn_start_deg,
        end=config.burn_end_deg,
        pa=piston_area: -_heat_release_rate_w(t, dp, q, start, end) / pa
    )
    piston.velocity = wall_velocity_fn
    piston.heat_flux = wall_heat_flux_fn

    sim = _prepare_simulation(ct, cylinder, remote, deg_per_sec)

    target_power_kw = float(row["power_kW"])
    target_power_w = target_power_kw * 1000.0
    target_torque_nm = target_power_w / (2.0 * pi * (RPM / 60.0))
    target_work_per_cyl_j = target_power_w * 120.0 / (RPM * ENGINE_CYLINDERS)

    fuel_flow_kg_s = float(row["fuelflow_kgh"]) / 3600.0
    fuel_mass_per_cyl_per_cycle = fuel_flow_kg_s / ENGINE_CYLINDERS / (RPM / 120.0)
    chemical_energy_per_cyl_cycle_j = fuel_mass_per_cyl_per_cycle * config.lhv_mj_per_kg * 1e6
    effective_heat_release_per_cyl_cycle_j = chemical_energy_per_cyl_cycle_j * config.combustion_efficiency
    implied_efficiency = target_work_per_cyl_j / chemical_energy_per_cyl_cycle_j

    print("=" * 94)
    print(f"STAGE 1.3 FUEL-METERED COMBUSTION DIAGNOSTIC - {case_label}")
    print("=" * 94)
    print("Fuel basis:")
    print(f"  fuel_name = {FUEL_NAME}")
    print(f"  lhv = {config.lhv_mj_per_kg:.3f} MJ/kg")
    print(f"  lhv_source = {config.lhv_source}")
    print(f"  lhv_status = {config.lhv_status}")
    print(f"  combustion_efficiency = {config.combustion_efficiency:.3f}")
    print(f"  ignition_center_deg = {config.ignition_center_deg:.1f}")
    print(f"  burn_start_deg = {config.burn_start_deg:.1f}")
    print(f"  burn_end_deg = {config.burn_end_deg:.1f}")
    print(f"  burn_window_deg = {config.burn_end_deg - config.burn_start_deg:.1f}")
    print(f"  burn_profile = {config.profile_name}")

    print("\nFuel and energy basis:")
    print(f"  fuel_mass_per_cyl_cycle = {fuel_mass_per_cyl_per_cycle * 1e6:.6f} mg")
    print(f"  chemical_energy_per_cyl_cycle = {chemical_energy_per_cyl_cycle_j:.6f} J")
    print(f"  effective_heat_release_per_cyl_cycle = {effective_heat_release_per_cyl_cycle_j:.6f} J")
    print(f"  implied_efficiency_vs_target = {implied_efficiency:.6f}")

    if log_window is not None:
        print("\nDetailed ignition logging window:")
        print(f"  theta_window = {log_window[0]:.1f} -> {log_window[1]:.1f} deg")

    history = {
        "theta": [],
        "pressure": [],
        "temperature": [],
        "mass": [],
        "volume": [],
        "mdot_in": [],
        "mdot_out": [],
        "burn_fraction": [],
        "heat_release_rate_W": [],
        "cumulative_heat_release_J": [],
    }
    ignition_records = []
    mass_ledger = {
        "start_of_cycle": None,
        "ivc": None,
        "burn_start": None,
        "ignition": None,
        "burn_center": None,
        "burn_end": None,
        "evo": None,
        "evc": None,
    }
    phase_ledger = {
        "0-228_intake": {
            "theta_start": 0.0,
            "theta_end": INTAKE_CLOSE_DEG,
            "mass_start": None,
            "mass_end": None,
            "delta_mass": 0.0,
            "integrated_inlet_mass": 0.0,
            "integrated_outlet_mass": 0.0,
            "fuel_mass_added": 0.0,
            "wall_mass_transfer": 0.0,
        },
        "228-320_sealed_compression": {
            "theta_start": INTAKE_CLOSE_DEG,
            "theta_end": BURN_START_DEG,
            "mass_start": None,
            "mass_end": None,
            "delta_mass": 0.0,
            "integrated_inlet_mass": 0.0,
            "integrated_outlet_mass": 0.0,
            "fuel_mass_added": 0.0,
            "wall_mass_transfer": 0.0,
        },
        "320-380_combustion": {
            "theta_start": BURN_START_DEG,
            "theta_end": BURN_END_DEG,
            "mass_start": None,
            "mass_end": None,
            "delta_mass": 0.0,
            "integrated_inlet_mass": 0.0,
            "integrated_outlet_mass": 0.0,
            "fuel_mass_added": 0.0,
            "wall_mass_transfer": 0.0,
        },
        "380-492_sealed_expansion": {
            "theta_start": BURN_END_DEG,
            "theta_end": EXHAUST_OPEN_DEG,
            "mass_start": None,
            "mass_end": None,
            "delta_mass": 0.0,
            "integrated_inlet_mass": 0.0,
            "integrated_outlet_mass": 0.0,
            "fuel_mass_added": 0.0,
            "wall_mass_transfer": 0.0,
        },
        "492-720_exhaust": {
            "theta_start": EXHAUST_OPEN_DEG,
            "theta_end": 720.0,
            "mass_start": None,
            "mass_end": None,
            "delta_mass": 0.0,
            "integrated_inlet_mass": 0.0,
            "integrated_outlet_mass": 0.0,
            "fuel_mass_added": 0.0,
            "wall_mass_transfer": 0.0,
        },
    }

    local_t = 0.0
    prev_theta = 0.0
    prev_p = cylinder.phase.P
    prev_v = cylinder.volume
    prev_mass = cylinder.mass
    prev_mdot_in = 0.0
    prev_mdot_out = 0.0
    prev_q = _heat_release_rate_w(0.0, deg_per_sec, effective_heat_release_per_cyl_cycle_j, config.burn_start_deg, config.burn_end_deg)
    prev_heat_fraction = _burn_fraction_at_time(0.0, deg_per_sec, config.burn_start_deg, config.burn_end_deg)
    total_work_j = 0.0
    pumping_work_j = 0.0
    compression_work_j = 0.0
    expansion_work_j = 0.0
    inducted_mass_kg = 0.0
    exhausted_mass_kg = 0.0
    integrated_heat_release_j = 0.0
    numerical_heat_release_j = 0.0

    m_initial = cylinder.phase.density * cylinder.volume
    p_at_ivc = None
    p_at_tdc = None
    t_at_tdc = None
    m_at_ivc = None
    m_at_tdc = None
    p_peak = None
    t_peak = None
    theta_peak_p = None
    theta_peak_t = None
    failure_message = None
    solver_stability = True
    fuel_mass_added_kg = 0.0
    wall_mass_transfer_kg = 0.0

    mass_ledger["start_of_cycle"] = {
        "theta_deg": 0.0,
        "mass_kg": m_initial,
        "pressure_pa": cylinder.phase.P,
        "temperature_k": cylinder.phase.T,
        "volume_m3": cylinder.volume,
    }

    ignition_printed = False

    for theta_target in theta_targets:
        target_t = theta_target * sec_per_deg
        _set_valves(theta_target, inlet_valve, outlet_valve)

        if (not ignition_printed) and theta_target >= config.burn_start_deg:
            try:
                p_pre = cylinder.phase.P
                t_pre = cylinder.phase.T
                m_pre = cylinder.phase.density * cylinder.volume
            except Exception:
                p_pre = cylinder.thermo.P
                t_pre = cylinder.thermo.T
                m_pre = cylinder.thermo.density * cylinder.volume
            print("\nPRE-COMBUSTION STATE:")
            print(f"  ignition_angle_deg = {config.ignition_center_deg:.1f}")
            print(f"  intake_valve_open = {is_valve_open(theta_target, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)}")
            print(f"  exhaust_valve_open = {is_valve_open(theta_target, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)}")
            print(f"  cylinder_mass = {m_pre:.9e} kg")
            print(f"  cylinder_volume = {cylinder.volume:.9e} m^3")
            print(f"  cylinder_pressure = {p_pre / 1e5:.6f} bar")
            print(f"  cylinder_temperature = {t_pre:.3f} K")
            ignition_printed = True

        try:
            sim.advance(target_t)
        except Exception as exc:
            solver_stability = False
            failure_message = f"{type(exc).__name__}: {exc}"
            print("\nSOLVER FAILURE:")
            print(f"  theta = {theta_target:.3f} deg")
            print(f"  time = {target_t:.8f} s")
            print(f"  error = {failure_message}")
            break

        try:
            p_curr = cylinder.phase.P
            t_curr = cylinder.phase.T
            rho_curr = cylinder.phase.density
            m_reactor_curr = cylinder.mass
        except Exception:
            p_curr = cylinder.thermo.P
            t_curr = cylinder.thermo.T
            rho_curr = cylinder.thermo.density
        v_curr = cylinder.volume
        try:
            m_reactor_curr
        except NameError:
            m_reactor_curr = rho_curr * v_curr
        mass_curr = m_reactor_curr
        mdot_in = inlet_valve.mass_flow_rate
        mdot_out = outlet_valve.mass_flow_rate
        qdot_w = _heat_release_rate_w(target_t, deg_per_sec, effective_heat_release_per_cyl_cycle_j, config.burn_start_deg, config.burn_end_deg)
        xb_curr = _burn_fraction_at_time(target_t, deg_per_sec, config.burn_start_deg, config.burn_end_deg)

        dW = 0.5 * (prev_p + p_curr) * (v_curr - prev_v)
        total_work_j += dW
        if theta_target < INTAKE_CLOSE_DEG or theta_target >= EXHAUST_OPEN_DEG:
            pumping_work_j += dW
        elif theta_target < 360.0:
            compression_work_j += dW
        else:
            expansion_work_j += dW

        dt = target_t - local_t
        if dt > 0.0:
            numerical_heat_release_j += 0.5 * (prev_q + qdot_w) * dt
            integrated_inlet = 0.5 * (prev_mdot_in + mdot_in) * dt
            integrated_outlet = 0.5 * (prev_mdot_out + mdot_out) * dt
            phase_key = None
            theta_mid = 0.5 * (prev_theta + theta_target)
            if theta_mid < INTAKE_CLOSE_DEG:
                phase_key = "0-228_intake"
            elif theta_mid < BURN_START_DEG:
                phase_key = "228-320_sealed_compression"
            elif theta_mid < BURN_END_DEG:
                phase_key = "320-380_combustion"
            elif theta_mid < EXHAUST_OPEN_DEG:
                phase_key = "380-492_sealed_expansion"
            else:
                phase_key = "492-720_exhaust"
            if phase_key is not None:
                phase_ledger[phase_key]["integrated_inlet_mass"] += integrated_inlet
                phase_ledger[phase_key]["integrated_outlet_mass"] += integrated_outlet
                phase_ledger[phase_key]["delta_mass"] += mass_curr - prev_mass

        local_t = target_t
        prev_q = qdot_w
        prev_v = v_curr
        prev_p = p_curr
        prev_theta = theta_target
        prev_mass = mass_curr
        prev_mdot_in = mdot_in
        prev_mdot_out = mdot_out

        inducted_mass_kg += mdot_in * dt
        exhausted_mass_kg += mdot_out * dt
        integrated_heat_release_j = effective_heat_release_per_cyl_cycle_j * xb_curr

        if abs(theta_target - INTAKE_CLOSE_DEG) < 5e-3:
            p_at_ivc = p_curr
            m_at_ivc = mass_curr
            phase_ledger["0-228_intake"]["mass_end"] = mass_curr
            phase_ledger["228-320_sealed_compression"]["mass_start"] = mass_curr
            mass_ledger["ivc"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }
        if abs(theta_target - config.burn_start_deg) < 5e-3:
            phase_ledger["228-320_sealed_compression"]["mass_end"] = mass_curr
            phase_ledger["320-380_combustion"]["mass_start"] = mass_curr
            mass_ledger["burn_start"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }
        if abs(theta_target - config.ignition_center_deg) < 5e-3:
            mass_ledger["ignition"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }
            print("\nIGNITION SNAPSHOT:")
            print(f"  ignition_angle_deg = {config.ignition_center_deg:.1f}")
            print(f"  intake_valve_open = {is_valve_open(theta_target, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)}")
            print(f"  exhaust_valve_open = {is_valve_open(theta_target, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)}")
            print(f"  cylinder_mass = {mass_curr:.9e} kg")
            print(f"  cylinder_volume = {v_curr:.9e} m^3")
            print(f"  cylinder_pressure = {p_curr / 1e5:.6f} bar")
            print(f"  cylinder_temperature = {t_curr:.3f} K")
        if abs(theta_target - config.ignition_center_deg) < 5e-3:
            mass_ledger["burn_center"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }
        if abs(theta_target - config.burn_end_deg) < 5e-3:
            phase_ledger["320-380_combustion"]["mass_end"] = mass_curr
            phase_ledger["380-492_sealed_expansion"]["mass_start"] = mass_curr
            mass_ledger["burn_end"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }
        if abs(theta_target - 720.0) < 5e-3:
            p_at_tdc = p_curr
            t_at_tdc = t_curr
            m_at_tdc = mass_curr
            phase_ledger["380-492_sealed_expansion"]["mass_end"] = mass_curr
            phase_ledger["492-720_exhaust"]["mass_start"] = mass_curr
        if abs(theta_target - EXHAUST_OPEN_DEG) < 5e-3:
            mass_ledger["evo"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }
        if abs(theta_target - EXHAUST_CLOSE_DEG) < 5e-3:
            phase_ledger["492-720_exhaust"]["mass_end"] = mass_curr
            mass_ledger["evc"] = {
                "theta_deg": theta_target,
                "mass_kg": mass_curr,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "volume_m3": v_curr,
            }

        if p_peak is None or p_curr > p_peak:
            p_peak = p_curr
            theta_peak_p = theta_target
        if t_peak is None or t_curr > t_peak:
            t_peak = t_curr
            theta_peak_t = theta_target

        history["theta"].append(theta_target)
        history["pressure"].append(p_curr)
        history["temperature"].append(t_curr)
        history["mass"].append(mass_curr)
        history["volume"].append(v_curr)
        history["mdot_in"].append(mdot_in)
        history["mdot_out"].append(mdot_out)
        history["burn_fraction"].append(xb_curr)
        history["heat_release_rate_W"].append(qdot_w)
        history["cumulative_heat_release_J"].append(integrated_heat_release_j)

        if log_window is not None and log_window[0] <= theta_target <= log_window[1]:
            rec = {
                "theta_deg": theta_target,
                "time_s": target_t,
                "pressure_pa": p_curr,
                "temperature_k": t_curr,
                "mass_kg": mass_curr,
                "heat_release_rate_w": qdot_w,
                "cumulative_heat_release_j": integrated_heat_release_j,
                "volume_m3": v_curr,
                "solver_status": "OK",
            }
            ignition_records.append(rec)
            print(
                "  theta={theta_deg:7.3f} deg  t={time_s: .8f} s  p={pressure_pa: .6f} Pa  "
                "T={temperature_k: .3f} K  m={mass_kg: .9e} kg  qdot={heat_release_rate_w: .3f} W  "
                "Qcum={cumulative_heat_release_j: .6f} J  V={volume_m3: .9e} m^3  status={solver_status}".format(
                    **rec
                )
            )

    for phase in phase_ledger.values():
        if phase["mass_start"] is None:
            phase["mass_start"] = m_initial if phase["theta_start"] == 0.0 else mass_curr
        if phase["mass_end"] is None:
            phase["mass_end"] = mass_curr
        phase["fuel_mass_added"] = fuel_mass_added_kg
        phase["wall_mass_transfer"] = wall_mass_transfer_kg

    flow_balance_error_kg = abs(
        mass_curr
        - (
            m_initial
            + inducted_mass_kg
            + fuel_mass_added_kg
            - exhausted_mass_kg
            + wall_mass_transfer_kg
        )
    )
    ledger_balance_error_kg = abs(
        mass_curr
        - (
            m_initial
            + sum(phase["integrated_inlet_mass"] for phase in phase_ledger.values())
            - sum(phase["integrated_outlet_mass"] for phase in phase_ledger.values())
            + fuel_mass_added_kg
            + wall_mass_transfer_kg
        )
    )
    mass_balance_error_kg = ledger_balance_error_kg
    mass_conservation_ok = mass_balance_error_kg < 1e-10
    heat_release_error_j = abs(integrated_heat_release_j - effective_heat_release_per_cyl_cycle_j)

    single_cyl_work_j = total_work_j
    engine_work_j = single_cyl_work_j * ENGINE_CYLINDERS
    engine_power_w = engine_work_j * RPM / 120.0
    engine_torque_nm = engine_work_j / (4.0 * pi)
    single_cyl_power_w = single_cyl_work_j * RPM / 120.0
    single_cyl_torque_nm = single_cyl_work_j / (4.0 * pi)

    power_err_pct = abs(engine_power_w / 1000.0 - target_power_kw) / target_power_kw * 100.0
    torque_err_pct = abs(engine_torque_nm - target_torque_nm) / target_torque_nm * 100.0

    print("\nSimulation results:")
    print(f"  fuel_mass_per_cyl_cycle = {fuel_mass_per_cyl_per_cycle * 1e6:.6f} mg")
    print(f"  prescribed_chemical_heat_release = {chemical_energy_per_cyl_cycle_j:.6f} J/cycle/cyl")
    print(f"  prescribed_effective_heat_release = {effective_heat_release_per_cyl_cycle_j:.6f} J/cycle/cyl")
    print(f"  integrated_heat_release_analytic = {integrated_heat_release_j:.6f} J/cycle/cyl")
    print(f"  integrated_heat_release_numerical = {numerical_heat_release_j:.6f} J/cycle/cyl")
    print(f"  heat_release_error = {heat_release_error_j:.6f} J")
    print(f"  peak_pressure = {p_peak / 1e5:.6f} bar at {theta_peak_p:.3f} deg")
    print(f"  peak_temperature = {t_peak:.2f} K at {theta_peak_t:.3f} deg")
    print(f"  net_work_per_cyl = {single_cyl_work_j:.6f} J/cycle/cyl")
    print(f"  predicted_engine_power = {engine_power_w / 1000.0:.6f} kW")
    print(f"  predicted_engine_torque = {engine_torque_nm:.6f} N-m")
    print(f"  target_power = {target_power_kw:.8f} kW")
    print(f"  target_torque = {target_torque_nm:.8f} N-m")
    print(f"  power_error_pct = {power_err_pct:.6f} %")
    print(f"  torque_error_pct = {torque_err_pct:.6f} %")
    print(f"  pumping_work = {pumping_work_j:.6f} J/cycle/cyl")
    print(f"  compression_work = {compression_work_j:.6f} J/cycle/cyl")
    print(f"  expansion_work = {expansion_work_j:.6f} J/cycle/cyl")
    print(f"  inducted_mass = {inducted_mass_kg * 1e3:.6f} g")
    print(f"  exhausted_mass = {exhausted_mass_kg * 1e3:.6f} g")
    print(f"  fuel_mass_added = {fuel_mass_added_kg * 1e6:.6f} mg")
    print(f"  wall_mass_transfer = {wall_mass_transfer_kg:.6e} kg")
    print(f"  trapped_mass_start = {m_initial * 1e3:.6f} g")
    print(f"  trapped_mass_end = {mass_curr * 1e3:.6f} g")
    print(f"  p_at_ivc = {p_at_ivc / 1e5 if p_at_ivc is not None else float('nan'):.6f} bar")
    print(f"  p_at_tdc = {p_at_tdc / 1e5 if p_at_tdc is not None else float('nan'):.6f} bar")
    print(f"  mass_balance_error_flow_sampled = {flow_balance_error_kg:.6e} kg")
    print(f"  mass_balance_error_ledger = {ledger_balance_error_kg:.6e} kg")
    print(f"  mass_balance_error = {mass_balance_error_kg:.6e} kg")
    print(f"  mass_conservation_ok = {mass_conservation_ok}")
    print(f"  solver_stability = {'PASS' if solver_stability else 'FAIL'}")
    if failure_message:
        print(f"  failure_message = {failure_message}")
    print("\nMass ledger:")
    for key in ("start_of_cycle", "ivc", "burn_start", "ignition", "burn_center", "burn_end", "evo", "evc"):
        entry = mass_ledger.get(key)
        if entry is None:
            print(f"  {key}: not reached in this diagnostic")
        else:
            print(
                "  {key}: theta={theta_deg:.1f} deg, mass={mass_kg:.9e} kg, p={pressure_pa:.6f} Pa, T={temperature_k:.3f} K, V={volume_m3:.9e} m^3".format(
                    key=key, **entry
                )
            )
    print("\nPhase ledger:")
    for key in ("0-228_intake", "228-320_sealed_compression", "320-380_combustion", "380-492_sealed_expansion", "492-720_exhaust"):
        phase = phase_ledger[key]
        print(
            "  {key}: theta={theta_start:.1f}->{theta_end:.1f} deg, mass={mass_start:.9e}->{mass_end:.9e} kg, "
            "delta_mass={delta_mass:.9e} kg, inlet_int={integrated_inlet_mass:.9e} kg, "
            "outlet_int={integrated_outlet_mass:.9e} kg".format(key=key, **phase)
        )
    print("\nContinuity check:")
    print(
        "  final_mass = initial_mass + intake_mass + fuel_mass_added - exhaust_mass + wall_mass_transfer"
    )
    print(f"  lhs_final_mass = {mass_curr:.9e} kg")
    print(f"  rhs_expected_mass = {m_initial + inducted_mass_kg + fuel_mass_added_kg - exhausted_mass_kg + wall_mass_transfer_kg:.9e} kg")
    print(f"  continuity_error = {mass_balance_error_kg:.9e} kg")

    return {
        "row": row,
        "config": config,
        "fuel_mass_per_cyl_per_cycle_kg": fuel_mass_per_cyl_per_cycle,
        "chemical_energy_per_cyl_cycle_j": chemical_energy_per_cyl_cycle_j,
        "effective_heat_release_per_cyl_cycle_j": effective_heat_release_per_cyl_cycle_j,
        "integrated_heat_release_j": integrated_heat_release_j,
        "integrated_heat_release_numerical_j": numerical_heat_release_j,
        "single_cyl_work_j": single_cyl_work_j,
        "single_cyl_power_w": single_cyl_power_w,
        "single_cyl_torque_nm": single_cyl_torque_nm,
        "engine_work_j": engine_work_j,
        "engine_power_w": engine_power_w,
        "engine_torque_nm": engine_torque_nm,
        "target_power_kw": target_power_kw,
        "target_torque_nm": target_torque_nm,
        "power_error_pct": power_err_pct,
        "torque_error_pct": torque_err_pct,
        "peak_pressure_pa": p_peak,
        "peak_pressure_theta_deg": theta_peak_p,
        "peak_temperature_k": t_peak,
        "peak_temperature_theta_deg": theta_peak_t,
        "pumping_work_j": pumping_work_j,
        "compression_work_j": compression_work_j,
        "expansion_work_j": expansion_work_j,
        "inducted_mass_kg": inducted_mass_kg,
        "exhausted_mass_kg": exhausted_mass_kg,
        "m_initial_kg": m_initial,
        "m_final_kg": mass_curr,
        "m_at_ivc_kg": m_at_ivc,
        "p_at_ivc_pa": p_at_ivc,
        "p_at_tdc_pa": p_at_tdc,
        "t_at_tdc_k": t_at_tdc,
        "m_at_tdc_kg": m_at_tdc,
        "mass_balance_error_kg": mass_balance_error_kg,
        "flow_balance_error_kg": flow_balance_error_kg,
        "ledger_balance_error_kg": ledger_balance_error_kg,
        "mass_conservation_ok": mass_conservation_ok,
        "heat_release_error_j": heat_release_error_j,
        "solver_stability": solver_stability,
        "failure_message": failure_message,
        "fuel_mass_added_kg": fuel_mass_added_kg,
        "wall_mass_transfer_kg": wall_mass_transfer_kg,
        "mass_ledger": mass_ledger,
        "phase_ledger": phase_ledger,
        "burn_start_deg": config.burn_start_deg,
        "burn_end_deg": config.burn_end_deg,
        "burn_window_deg": config.burn_end_deg - config.burn_start_deg,
        "burn_profile": config.profile_name,
        "history": history,
        "ignition_records": ignition_records,
    }


def run_short_combustion_window_diagnostic() -> dict:
    import cantera as ct

    row = load_target_row(CSV_PATH)
    config = CombustionConfig(
        lhv_mj_per_kg=LHV_MJ_PER_KG,
        lhv_source=LHV_SOURCE,
        lhv_status=LHV_STATUS,
        combustion_efficiency=COMBUSTION_EFFICIENCY,
        ignition_center_deg=IGNITION_CENTER_DEG,
        burn_start_deg=BURN_START_DEG,
        burn_end_deg=BURN_END_DEG,
        profile_name=PROFILE_NAME,
    )

    # Advance to the verified pre-ignition point first, then inspect the combustion window densely.
    theta_targets = [float(theta) for theta in range(1, int(BURN_START_DEG) + 1)]
    theta_targets.extend(
        round(theta, 10)
        for theta in build_theta_schedule(BURN_END_DEG, coarse_step_deg=1.0, dense_step_deg=0.1)
        if theta >= BURN_START_DEG
    )
    # De-duplicate while preserving order.
    ordered: list[float] = []
    for theta in theta_targets:
        if not ordered or abs(ordered[-1] - theta) > 1e-12:
            ordered.append(theta)

    return _advance_case(
        ct=ct,
        row=row,
        config=config,
        theta_targets=ordered,
        log_window=(BURN_START_DEG, BURN_END_DEG),
        case_label="SHORT COMBUSTION-WINDOW DIAGNOSTIC",
        detailed_window=True,
    )


def run_fuel_metered_combustion() -> dict:
    import cantera as ct

    row = load_target_row(CSV_PATH)
    config = CombustionConfig(
        lhv_mj_per_kg=LHV_MJ_PER_KG,
        lhv_source=LHV_SOURCE,
        lhv_status=LHV_STATUS,
        combustion_efficiency=COMBUSTION_EFFICIENCY,
        ignition_center_deg=IGNITION_CENTER_DEG,
        burn_start_deg=BURN_START_DEG,
        burn_end_deg=BURN_END_DEG,
        profile_name=PROFILE_NAME,
    )

    theta_targets = build_theta_schedule(720.0, coarse_step_deg=1.0, dense_step_deg=0.1)
    exhaust_dense_windows = (
        (EXHAUST_OPEN_DEG, EXHAUST_OPEN_DEG + 48.0),
        (EXHAUST_CLOSE_DEG - 30.0, EXHAUST_CLOSE_DEG),
    )
    for dense_start, dense_end in exhaust_dense_windows:
        theta_targets.extend(
            round(theta, 10)
            for theta in build_theta_schedule(
                dense_end,
                coarse_step_deg=1.0,
                dense_start_deg=dense_start,
                dense_end_deg=dense_end,
                dense_step_deg=0.1,
            )
            if dense_start <= theta <= dense_end
        )
    theta_targets = sorted(set(round(theta, 10) for theta in theta_targets))
    return _advance_case(
        ct=ct,
        row=row,
        config=config,
        theta_targets=theta_targets,
        log_window=(BURN_START_DEG, BURN_END_DEG),
        case_label="FULL CYCLE RUN",
        detailed_window=True,
    )


def main() -> int:
    short_result = run_short_combustion_window_diagnostic()
    print("\nSHORT WINDOW SUMMARY")
    print(f"  solver_stability = {'PASS' if short_result['solver_stability'] else 'FAIL'}")
    print(f"  heat_release_error = {short_result['heat_release_error_j']:.6e} J")
    print(f"  integrated_heat_release = {short_result['integrated_heat_release_j']:.6f} J")
    print(f"  prescribed_effective_heat_release = {short_result['effective_heat_release_per_cyl_cycle_j']:.6f} J")
    if not short_result["solver_stability"]:
        print("  full_cycle_run = SKIPPED")
        return 1

    full_result = run_fuel_metered_combustion()
    print("\nFULL CYCLE SUMMARY")
    print(f"  solver_stability = {'PASS' if full_result['solver_stability'] else 'FAIL'}")
    print(f"  mass_conservation = {'PASS' if full_result['mass_conservation_ok'] else 'FAIL'}")
    print(f"  power_error_pct = {full_result['power_error_pct']:.6f} %")
    print(f"  torque_error_pct = {full_result['torque_error_pct']:.6f} %")
    print(f"  heat_release_error = {full_result['heat_release_error_j']:.6e} J")
    return 0 if full_result["solver_stability"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
