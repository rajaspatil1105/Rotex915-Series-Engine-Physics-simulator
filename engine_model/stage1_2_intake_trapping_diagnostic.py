"""
Stage 1.2: Intake Trapping Diagnostic (diagnostic-only)

Objective:
Determine why the cylinder enters compression with only ~5.48e-5 kg of trapped charge
instead of roughly 4.50e-4 kg.

Setup:
- Start at theta = 0 deg (TDC, V = Vc)
- Validated Cantera Wall piston kinematics
- Intake valve open during existing intended intake window (0 deg to 228 deg absolute)
- Exhaust valve using currently established timing (132 deg to 0/360/720 deg)
- Log whether and when exhaust overlaps intake
- Measure mdot_in, mdot_out, cumulative masses, cylinder state at every crank degree
- Check state at IVC (228 deg)
- Compress through sealed compression stroke to TDC (360 deg)
- Record final TDC pressure and temperature
"""

from math import pi, cos, sin, radians
import sys

# Official Rotax 915 iS single-cylinder geometry
ROTAX_GEOMETRY = {
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "compression_ratio": 8.2,
}

RPM = 3000
AMBIENT_P = 101325.0  # Pa
AMBIENT_T = 288.15    # K
MECH = 'gri30.yaml'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'
AIR_COMPOSITION = 'O2:0.21, N2:0.79'
STEP_DEG = 1.0

# Phase-0 provisional calibration valve timing parameters
PHASE0_TIMING = {
    "intake_open_deg_TDC": 0.0,
    "intake_close_deg_ABDC": 48.0,
    "exhaust_open_deg_BBDC": 48.0,
    "exhaust_close_deg_TDC": 0.0,
}

# Absolute crank angle mapping in Phase-0 (0..720 deg, 0 = TDC firing/intake start)
INTAKE_OPEN_DEG = PHASE0_TIMING["intake_open_deg_TDC"]               # 0.0 deg
INTAKE_CLOSE_DEG = 180.0 + PHASE0_TIMING["intake_close_deg_ABDC"]   # 228.0 deg
EXHAUST_OPEN_DEG = 180.0 - PHASE0_TIMING["exhaust_open_deg_BBDC"]   # 132.0 deg
EXHAUST_CLOSE_DEG = PHASE0_TIMING["exhaust_close_deg_TDC"]          # 0.0 / 360.0 / 720.0 deg

# Established valve coefficients
VALVE_COEFF_OPEN_BASE = 1.0e-6  # original Stage 1.2 baseline
VALVE_COEFF_OPEN_MOTORING = 1.0e-3  # motoring diagnostic value
VALVE_COEFF_CLOSED = 0.0


def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * (bore_m ** 2) * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


def is_valve_open(theta_deg: float, open_deg: float, close_deg: float) -> bool:
    theta = theta_deg % 720.0
    if close_deg > open_deg:
        return open_deg <= theta < close_deg
    elif close_deg < open_deg:
        return (theta >= open_deg) or (theta < close_deg)
    else:
        return False


def run_intake_trapping_simulation(valve_coeff_open: float = 1.0e-3, label: str = "Diagnostic"):
    import cantera as ct

    print("=" * 75)
    print(f"RUNNING INTAKE TRAPPING DIAGNOSTIC [{label}] (Valve Coeff = {valve_coeff_open:.1e} kg/s/Pa)")
    print("=" * 75)

    g = ROTAX_GEOMETRY
    bore = g['bore_m']
    stroke = g['stroke_m']
    cr = g['compression_ratio']

    Vd = swept_volume_per_cylinder(bore, stroke)
    Vc = clearance_volume_from_cr(Vd, cr)
    V_TDC = cyl_volume_at_theta(Vd, Vc, 0.0)
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    piston_area = (pi / 4.0) * (bore ** 2)

    print(f"Displacement (Vd): {Vd*1e6:.3f} cc | Clearance (Vc): {Vc*1e6:.3f} cc | CR: {cr:.2f}")
    print(f"V(0° TDC) = {V_TDC*1e6:.3f} cc | V(180° BDC) = {V_BDC*1e6:.3f} cc")

    # Valve timing window checks
    print(f"\nValve Timing Windows (Absolute crank angle 0°..720°):")
    print(f"  Intake Window:  {INTAKE_OPEN_DEG:.1f}° to {INTAKE_CLOSE_DEG:.1f}° (Duration: {INTAKE_CLOSE_DEG - INTAKE_OPEN_DEG:.1f}°)")
    print(f"  Exhaust Window: {EXHAUST_OPEN_DEG:.1f}° to {EXHAUST_CLOSE_DEG:.1f}° (starts at {EXHAUST_OPEN_DEG:.1f}°, closes at {EXHAUST_CLOSE_DEG:.1f}° / 720°)")

    # Overlap detection
    overlap_angles = [th for th in range(720) if is_valve_open(th, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG) and is_valve_open(th, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)]
    if overlap_angles:
        print(f"  [!] CRITICAL VALVE OVERLAP DETECTED: {len(overlap_angles)} degrees open simultaneously!")
        print(f"      Overlap range: {overlap_angles[0]:.1f}° to {overlap_angles[-1]:.1f}° ({overlap_angles[0]}°..{overlap_angles[-1]+1}°)")
    else:
        print(f"  No valve overlap detected.")

    # Create Gas Solution
    try:
        gas_cyl = ct.Solution(MECH)
    except Exception:
        gas_cyl = ct.Solution('gri30')
    gas_cyl.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    # Initial Cylinder Reactor at theta = 0 deg (TDC)
    cylinder = ct.IdealGasReactor(gas_cyl, clone=False)
    cylinder.volume = V_TDC
    m_initial_TDC = cylinder.phase.density * cylinder.volume

    print(f"\nInitial State at 0° TDC:")
    print(f"  P0 = {cylinder.phase.P/1e5:.5f} bar | T0 = {cylinder.phase.T:.2f} K | rho0 = {cylinder.phase.density:.4f} kg/m^3")
    print(f"  Initial Cylinder Mass at TDC (in Vc): {m_initial_TDC:.8e} kg ({m_initial_TDC*1e3:.4f} g)")
    m_full_BDC_ambient = cylinder.phase.density * V_BDC
    print(f"  Reference full-charge Mass at BDC:    {m_full_BDC_ambient:.8e} kg ({m_full_BDC_ambient*1e3:.4f} g)")

    # Remote passive reactor for Wall piston
    gas_remote = ct.Solution(MECH)
    gas_remote.TP = AMBIENT_T, AMBIENT_P
    remote = ct.IdealGasReactor(gas_remote, clone=False)
    remote.volume = 1.0

    piston = ct.Wall(cylinder, remote)
    piston.area = piston_area

    # Intake Reservoir and Valve
    gas_inlet = ct.Solution(MECH)
    gas_inlet.TPX = AMBIENT_T, AMBIENT_P, AIR_COMPOSITION
    try:
        inlet_res = ct.Reservoir(gas_inlet, clone=False)
    except TypeError:
        inlet_res = ct.Reservoir(gas_inlet)
    inlet_valve = ct.Valve(inlet_res, cylinder)

    # Exhaust Reservoir and Valve
    gas_outlet = ct.Solution(MECH)
    gas_outlet.TPX = AMBIENT_T, AMBIENT_P, AIR_COMPOSITION
    try:
        outlet_res = ct.Reservoir(gas_outlet, clone=False)
    except TypeError:
        outlet_res = ct.Reservoir(gas_outlet)
    outlet_valve = ct.Valve(cylinder, outlet_res)

    sim = ct.ReactorNet([cylinder, remote])
    sim.initialize()

    deg_per_sec = RPM * 360.0 / 60.0  # 18000 deg/s
    sec_per_deg = 1.0 / deg_per_sec
    dt = STEP_DEG * sec_per_deg

    try:
        sim.max_time_step = sec_per_deg / 50.0
    except Exception:
        pass

    # Simulation arrays
    history = {
        'theta': [],
        'volume': [],
        'pressure': [],
        'temperature': [],
        'density': [],
        'mass': [],
        'inlet_open': [],
        'outlet_open': [],
        'mdot_in': [],
        'mdot_out': [],
        'cum_m_in': [],
        'cum_m_out': [],
    }

    cum_m_in = 0.0
    cum_m_out = 0.0
    local_t = 0.0

    # Total steps: 0 deg to 360 deg (Intake 0..180..228, then Compression 228..360)
    # We can run a full 360 deg stroke (Intake + Compression)
    total_steps = int(360.0 / STEP_DEG)

    peak_mdot_in = 0.0
    peak_mdot_in_theta = 0.0
    peak_mdot_out = 0.0
    peak_mdot_out_theta = 0.0

    m_at_IVC = None
    P_at_IVC = None
    T_at_IVC = None
    V_at_IVC = None

    for s in range(total_steps + 1):
        theta = s * STEP_DEG

        # Measure current state before step
        rho = cylinder.phase.density
        vol = cylinder.volume
        P = cylinder.phase.P
        T = cylinder.phase.T
        mass = rho * vol

        in_open = is_valve_open(theta, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)
        out_open = is_valve_open(theta, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)

        # Set valve coefficients
        inlet_valve.valve_coeff = valve_coeff_open if in_open else VALVE_COEFF_CLOSED
        outlet_valve.valve_coeff = valve_coeff_open if out_open else VALVE_COEFF_CLOSED

        # Flow rates
        mdot_in = inlet_valve.mass_flow_rate
        mdot_out = outlet_valve.mass_flow_rate

        if mdot_in > peak_mdot_in:
            peak_mdot_in = mdot_in
            peak_mdot_in_theta = theta

        if mdot_out > peak_mdot_out:
            peak_mdot_out = mdot_out
            peak_mdot_out_theta = theta

        history['theta'].append(theta)
        history['volume'].append(vol)
        history['pressure'].append(P)
        history['temperature'].append(T)
        history['density'].append(rho)
        history['mass'].append(mass)
        history['inlet_open'].append(in_open)
        history['outlet_open'].append(out_open)
        history['mdot_in'].append(mdot_in)
        history['mdot_out'].append(mdot_out)
        history['cum_m_in'].append(cum_m_in)
        history['cum_m_out'].append(cum_m_out)

        # Record state at IVC (theta == INTAKE_CLOSE_DEG)
        if abs(theta - INTAKE_CLOSE_DEG) < 1e-5:
            m_at_IVC = mass
            P_at_IVC = P
            T_at_IVC = T
            V_at_IVC = vol

        if s == total_steps:
            break

        # Compute piston velocity for step [theta -> theta + STEP_DEG]
        V_next = cyl_volume_at_theta(Vd, Vc, theta + STEP_DEG)
        V_curr = cyl_volume_at_theta(Vd, Vc, theta)
        delta_V = V_next - V_curr
        vel = (delta_V / dt) / piston_area
        piston.velocity = vel

        # Advance ReactorNet
        local_t += dt
        sim.advance(local_t)

        # Accumulate mass flows
        cum_m_in += mdot_in * dt
        cum_m_out += mdot_out * dt

    # Final state at 360 deg (TDC after compression)
    idx_360 = history['theta'].index(360.0)
    P_TDC_final = history['pressure'][idx_360]
    T_TDC_final = history['temperature'][idx_360]
    m_TDC_final = history['mass'][idx_360]
    V_TDC_final = history['volume'][idx_360]

    # Theoretical compression pressure based on ACTUAL trapped mass at IVC
    # Ideal gas law: P = (m_trapped * R_spec * T) / V
    # For isentropic compression of trapped mass from V_IVC, T_IVC, P_IVC to V_TDC:
    # P_theory = P_IVC * (V_IVC / V_TDC)^gamma
    gas_ivc = ct.Solution(MECH)
    gas_ivc.TP = T_at_IVC, P_at_IVC
    gamma_ivc = gas_ivc.cp_mass / gas_ivc.cv_mass
    P_theory_actual_trapped_const_gamma = P_at_IVC * ((V_at_IVC / V_TDC_final) ** gamma_ivc)

    # Exact Cantera isentropic compression of actual trapped mass
    gas_exact = ct.Solution(MECH)
    gas_exact.TP = T_at_IVC, P_at_IVC
    s_ivc = gas_exact.s
    v_sp_ivc = gas_exact.v
    v_sp_tdc = v_sp_ivc * (V_TDC_final / V_at_IVC)
    gas_exact.SV = s_ivc, v_sp_tdc
    P_theory_actual_trapped_exact = gas_exact.P
    T_theory_actual_trapped_exact = gas_exact.T

    # Also reference theoretical P2 if full charge was trapped (CR=8.2 from 1 bar)
    gas_ref = ct.Solution(MECH)
    gas_ref.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION
    gas_ref.SV = gas_ref.s, gas_ref.v / cr
    P_theory_full_charge = gas_ref.P

    print("\n" + "=" * 75)
    print(f"DIAGNOSTIC MEASUREMENT RESULTS [{label}]")
    print("=" * 75)
    print("1. Valve Timing & Overlap:")
    print(f"   - Intake Open Window:       {INTAKE_OPEN_DEG:.1f}° to {INTAKE_CLOSE_DEG:.1f}°")
    print(f"   - Exhaust Open Window:      {EXHAUST_OPEN_DEG:.1f}° to {EXHAUST_CLOSE_DEG:.1f}°")
    print(f"   - Valve Overlap Window:     {overlap_angles[0]:.1f}° to {overlap_angles[-1]+1:.1f}° (Duration: {len(overlap_angles)}°)")
    print(f"   - Peak Intake mdot:         {peak_mdot_in:.6e} kg/s at theta = {peak_mdot_in_theta:.1f}°")
    print(f"   - Peak Exhaust mdot:        {peak_mdot_out:.6e} kg/s at theta = {peak_mdot_out_theta:.1f}°")

    print("\n2. Mass Flow & Trapping Accounting:")
    print(f"   - Initial Mass at 0° TDC:   {m_initial_TDC:.10e} kg ({m_initial_TDC*1e3:.4f} g)")
    print(f"   - Total Induced (Intake):   {cum_m_in:.10e} kg ({cum_m_in*1e3:.4f} g)")
    print(f"   - Total Expelled (Exhaust): {cum_m_out:.10e} kg ({cum_m_out*1e3:.4f} g)")
    print(f"   - Mass at IVC (228° ABDC):  {m_at_IVC:.10e} kg ({m_at_IVC*1e3:.4f} g)")
    print(f"   - Reference Full BDC Mass:  {m_full_BDC_ambient:.10e} kg ({m_full_BDC_ambient*1e3:.4f} g)")
    print(f"   - Trapped Mass / Full BDC:  {(m_at_IVC / m_full_BDC_ambient) * 100.0:.2f} %")

    print("\n3. State at Intake Valve Closing (IVC = 228°):")
    print(f"   - Volume at IVC:            {V_at_IVC*1e6:.3f} cc (Effective Vol Ratio to TDC = {V_at_IVC/V_TDC_final:.4f})")
    print(f"   - Pressure at IVC:          {P_at_IVC/1e5:.5f} bar ({P_at_IVC:.2f} Pa)")
    print(f"   - Temperature at IVC:       {T_at_IVC:.2f} K")
    print(f"   - Trapped Mass at IVC:      {m_at_IVC:.10e} kg")

    print("\n4. State at TDC after Sealed Compression (360°):")
    print(f"   - Simulated P at TDC:       {P_TDC_final/1e5:.5f} bar ({P_TDC_final:.2f} Pa)")
    print(f"   - Simulated T at TDC:       {T_TDC_final:.2f} K")
    print(f"   - Final Mass at TDC:        {m_TDC_final:.10e} kg")
    print(f"   - Trapping Mass Error:      {abs(m_TDC_final - m_at_IVC):.10e} kg")

    print("\n5. Theoretical Pressure Comparison:")
    print(f"   - Theoretical P (Full Charge CR=8.2):              {P_theory_full_charge/1e5:.4f} bar")
    print(f"   - Theoretical P (Based on Actual Trapped Mass):    {P_theory_actual_trapped_exact/1e5:.4f} bar")
    print(f"   - Simulated P / Theory(Actual Trapped Mass):       {P_TDC_final / P_theory_actual_trapped_exact:.6f} ({P_TDC_final / P_theory_actual_trapped_exact * 100.0:.2f} %)")

    print("\n6. Crank Angle Trace Sample (every 15°):")
    print(f"  {'theta':>5} | {'V (cc)':>8} | {'P (bar)':>8} | {'T (K)':>7} | {'Mass (g)':>9} | {'Inlet':>6} | {'Outlet':>6} | {'mdot_in (kg/s)':>14} | {'mdot_out (kg/s)':>14}")
    print("  " + "-" * 105)
    for th in range(0, 361, 15):
        idx = history['theta'].index(float(th))
        print(f"  {th:5.1f} | {history['volume'][idx]*1e6:8.2f} | {history['pressure'][idx]/1e5:8.4f} | {history['temperature'][idx]:7.2f} | {history['mass'][idx]*1e3:9.5f} | {str(history['inlet_open'][idx]):>6} | {str(history['outlet_open'][idx]):>6} | {history['mdot_in'][idx]:14.4e} | {history['mdot_out'][idx]:14.4e}")

    return {
        'label': label,
        'valve_coeff_open': valve_coeff_open,
        'overlap_duration_deg': len(overlap_angles),
        'overlap_start_deg': overlap_angles[0] if overlap_angles else None,
        'overlap_end_deg': overlap_angles[-1] if overlap_angles else None,
        'peak_mdot_in': peak_mdot_in,
        'peak_mdot_in_theta': peak_mdot_in_theta,
        'peak_mdot_out': peak_mdot_out,
        'peak_mdot_out_theta': peak_mdot_out_theta,
        'm_initial_TDC': m_initial_TDC,
        'cum_m_in': cum_m_in,
        'cum_m_out': cum_m_out,
        'm_at_IVC': m_at_IVC,
        'P_at_IVC': P_at_IVC,
        'T_at_IVC': T_at_IVC,
        'V_at_IVC': V_at_IVC,
        'm_TDC_final': m_TDC_final,
        'P_TDC_final': P_TDC_final,
        'T_TDC_final': T_TDC_final,
        'P_theory_actual_trapped_exact': P_theory_actual_trapped_exact,
        'P_theory_full_charge': P_theory_full_charge,
        'ratio_sim_to_actual_theory': P_TDC_final / P_theory_actual_trapped_exact,
    }


def main():
    print("=" * 75)
    print("STAGE 1.2 INTAKE TRAPPING & VALVE TIMING DIAGNOSTIC SUITE")
    print("=" * 75)

    # Test 1: Established Phase-0 timing with valve_coeff = 1.0e-3 (motoring diagnostic value)
    res_1e3 = run_intake_trapping_simulation(valve_coeff_open=1.0e-3, label="Phase-0 Established Timing (coeff=1e-3)")

    # Test 2: Established Phase-0 timing with valve_coeff = 1.0e-6 (original gas exchange baseline)
    res_1e6 = run_intake_trapping_simulation(valve_coeff_open=1.0e-6, label="Phase-0 Established Timing (coeff=1e-6)")


if __name__ == '__main__':
    main()
