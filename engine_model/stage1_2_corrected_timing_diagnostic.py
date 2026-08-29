"""
Stage 1.2: Corrected Valve Timing Motoring Diagnostic (diagnostic-only)

Purpose:
Test and verify the corrected 4-stroke valve timing mapping in Cantera 3.2.0:
- Intake: 0.0 deg (TDC) -> 228.0 deg (48 deg ABDC)
- Compression: 228.0 deg -> 360.0 deg (BOTH VALVES CLOSED)
- Expansion: 360.0 deg -> 492.0 deg (BOTH VALVES CLOSED)
- Exhaust: 492.0 deg (48 deg BBDC) -> 720.0 deg (TDC)

Maintains:
- Official Rotax 915 iS geometry (Bore=84mm, Stroke=61mm, CR=8.2)
- Validated Cantera Wall piston implementation
- Reservoir states at ambient (101325 Pa, 288.15 K)
- Combustion/ignition OFF (motoring)
- Step size = 1.0 deg CA over 1 full 720-deg cycle
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

# Phase-0 provisional calibration parameters
PHASE0_TIMING = {
    "intake_open_deg_TDC": 0.0,
    "intake_close_deg_ABDC": 48.0,
    "exhaust_open_deg_BBDC": 48.0,
    "exhaust_close_deg_TDC": 0.0,
}

# CORRECTED Absolute crank-angle mapping (0..720 deg)
INTAKE_OPEN_DEG = PHASE0_TIMING["intake_open_deg_TDC"]                 # 0.0 deg
INTAKE_CLOSE_DEG = 180.0 + PHASE0_TIMING["intake_close_deg_ABDC"]     # 228.0 deg
EXHAUST_OPEN_DEG = 540.0 - PHASE0_TIMING["exhaust_open_deg_BBDC"]     # 492.0 deg (540 - 48)
EXHAUST_CLOSE_DEG = 720.0 + PHASE0_TIMING["exhaust_close_deg_TDC"]    # 720.0 deg (or 0.0 deg wrap)

# Valve flow coefficients
VALVE_COEFF_OPEN = 1.0e-3  # Diagnostic open valve coefficient
VALVE_COEFF_CLOSED = 0.0


def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * (bore_m ** 2) * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    # 0 deg = TDC (Vc), 180 deg = BDC (Vc + Vd), 360 deg = TDC (Vc), 540 deg = BDC, 720 deg = TDC
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


def run_corrected_timing_diagnostic():
    import cantera as ct

    print("=" * 80)
    print("STAGE 1.2: CORRECTED VALVE TIMING MOTORING DIAGNOSTIC")
    print(f"Cantera Version: {ct.__version__}")
    print("=" * 80)

    # 1. Geometry Setup & Verification
    g = ROTAX_GEOMETRY
    bore = g['bore_m']
    stroke = g['stroke_m']
    cr = g['compression_ratio']

    Vd = swept_volume_per_cylinder(bore, stroke)
    Vc = clearance_volume_from_cr(Vd, cr)
    V_TDC = cyl_volume_at_theta(Vd, Vc, 0.0)
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    piston_area = (pi / 4.0) * (bore ** 2)

    print("\n--- 1. GEOMETRY & ENGINE PARAMETERS ---")
    print(f"Bore:               {bore * 1000.0:.3f} mm")
    print(f"Stroke:             {stroke * 1000.0:.3f} mm")
    print(f"Displacement (Vd):  {Vd * 1e6:.4f} cc")
    print(f"Clearance (Vc):     {Vc * 1e6:.4f} cc")
    print(f"V_max (BDC):        {V_BDC * 1e6:.4f} cc")
    print(f"V_min (TDC):        {V_TDC * 1e6:.4f} cc")
    print(f"Compression Ratio:  {V_BDC / V_TDC:.4f} (Target: {cr:.2f})")
    print(f"Piston Area:        {piston_area * 1e4:.4f} cm^2")
    print(f"Engine Speed:       {RPM} RPM")

    # 2. Timing Window Verification & Sealed Interval Check
    print("\n--- 2. VALVE TIMING WINDOWS & SEALED INTERVAL VERIFICATION ---")
    print(f"Intake Valve Window:   {INTAKE_OPEN_DEG:.1f}° to {INTAKE_CLOSE_DEG:.1f}° (Duration: {INTAKE_CLOSE_DEG - INTAKE_OPEN_DEG:.1f}°)")
    print(f"Exhaust Valve Window:  {EXHAUST_OPEN_DEG:.1f}° to {EXHAUST_CLOSE_DEG:.1f}° (Duration: {EXHAUST_CLOSE_DEG - EXHAUST_OPEN_DEG:.1f}°)")

    # Check for overlap and sealed interval
    overlap_angles = [th for th in range(720) if is_valve_open(th, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG) and is_valve_open(th, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)]
    sealed_angles = [th for th in range(720) if (not is_valve_open(th, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)) and (not is_valve_open(th, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG))]

    print(f"Intake/Exhaust Overlap: {len(overlap_angles)} deg ({'NONE (PASS)' if len(overlap_angles) == 0 else 'FAIL'})")
    print(f"Sealed Interval:        {sealed_angles[0]:.1f}° to {sealed_angles[-1]+1:.1f}° (Duration: {len(sealed_angles)}°)")
    print(f"  - Compression Sealed: 228.0° to 360.0° (132° sealed) -> {'PASS' if all(th in sealed_angles for th in range(228, 360)) else 'FAIL'}")
    print(f"  - Expansion Sealed:   360.0° to 492.0° (132° sealed) -> {'PASS' if all(th in sealed_angles for th in range(360, 492)) else 'FAIL'}")

    # 3. Create Cantera Reactors and Piston Wall
    try:
        gas_cyl = ct.Solution(MECH)
    except Exception:
        gas_cyl = ct.Solution('gri30')
    gas_cyl.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    cylinder = ct.IdealGasReactor(gas_cyl, clone=False)
    cylinder.volume = V_TDC  # Start at 0 deg TDC
    m_initial_TDC = cylinder.phase.density * cylinder.volume

    # Remote buffer reactor for Wall piston
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

    # 4. Simulation Arrays
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
    total_steps = int(720.0 / STEP_DEG)

    peak_mdot_in = 0.0
    peak_mdot_in_theta = 0.0
    peak_mdot_out = 0.0
    peak_mdot_out_theta = 0.0

    exhaust_flow_during_compression = 0.0

    m_at_IVC = None
    P_at_IVC = None
    T_at_IVC = None
    V_at_IVC = None

    # 5. Run 720-deg Full Cycle
    for s in range(total_steps + 1):
        theta = s * STEP_DEG

        # Measure current state
        rho = cylinder.phase.density
        vol = cylinder.volume
        P = cylinder.phase.P
        T = cylinder.phase.T
        mass = rho * vol

        in_open = is_valve_open(theta, INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG)
        out_open = is_valve_open(theta, EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG)

        inlet_valve.valve_coeff = VALVE_COEFF_OPEN if in_open else VALVE_COEFF_CLOSED
        outlet_valve.valve_coeff = VALVE_COEFF_OPEN if out_open else VALVE_COEFF_CLOSED

        mdot_in = inlet_valve.mass_flow_rate
        mdot_out = outlet_valve.mass_flow_rate

        if mdot_in > peak_mdot_in:
            peak_mdot_in = mdot_in
            peak_mdot_in_theta = theta

        if mdot_out > peak_mdot_out:
            peak_mdot_out = mdot_out
            peak_mdot_out_theta = theta

        # Check for unintended exhaust flow during compression (228..360)
        if 228.0 <= theta <= 360.0:
            if mdot_out > 1e-12:
                exhaust_flow_during_compression += mdot_out * dt

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

        # Record state at IVC (228.0 deg)
        if abs(theta - INTAKE_CLOSE_DEG) < 1e-5:
            m_at_IVC = mass
            P_at_IVC = P
            T_at_IVC = T
            V_at_IVC = vol

        if s == total_steps:
            break

        # Compute exact velocity to achieve target discrete volume change over dt
        V_next = cyl_volume_at_theta(Vd, Vc, theta + STEP_DEG)
        V_curr = cyl_volume_at_theta(Vd, Vc, theta)
        delta_V = V_next - V_curr
        vel = (delta_V / dt) / piston_area
        piston.velocity = vel

        # Advance ReactorNet
        local_t += dt
        sim.advance(local_t)

        cum_m_in += mdot_in * dt
        cum_m_out += mdot_out * dt

    # 6. Extract Critical Cycle Metrics
    thetas = history['theta']
    pressures = history['pressure']
    temperatures = history['temperature']
    masses = history['mass']
    volumes = history['volume']

    idx_360 = thetas.index(360.0)  # Compression TDC
    P_TDC_360 = pressures[idx_360]
    T_TDC_360 = temperatures[idx_360]
    m_TDC_360 = masses[idx_360]
    V_TDC_360 = volumes[idx_360]

    idx_peak_P = pressures.index(max(pressures))
    P_peak = pressures[idx_peak_P]
    theta_peak_P = thetas[idx_peak_P]
    P_min = min(pressures)
    theta_min_P = thetas[pressures.index(P_min)]

    # Mass conservation during sealed compression (228 -> 360)
    idx_ivc = thetas.index(228.0)
    masses_compression = masses[idx_ivc:idx_360 + 1]
    max_mass_dev_compression = max(abs(m - m_at_IVC) for m in masses_compression)
    mass_conservation_error_compression_pct = (max_mass_dev_compression / m_at_IVC) * 100.0

    # 7. Theoretical Compression Calculation based on ACTUAL Trapped Mass & IVC State
    # Effective volume ratio from IVC to TDC
    r_eff_IVC_to_TDC = V_at_IVC / V_TDC_360

    # Constant gamma theoretical estimate from IVC state
    gas_ivc = ct.Solution(MECH)
    gas_ivc.TP = T_at_IVC, P_at_IVC
    gamma_ivc = gas_ivc.cp_mass / gas_ivc.cv_mass
    P_theory_const_gamma = P_at_IVC * (r_eff_IVC_to_TDC ** gamma_ivc)
    T_theory_const_gamma = T_at_IVC * (r_eff_IVC_to_TDC ** (gamma_ivc - 1.0))

    # Exact Cantera isentropic compression of actual trapped mass from IVC state
    gas_exact = ct.Solution(MECH)
    gas_exact.TP = T_at_IVC, P_at_IVC
    s_ivc = gas_exact.s
    v_sp_ivc = gas_exact.v
    v_sp_tdc = v_sp_ivc / r_eff_IVC_to_TDC
    gas_exact.SV = s_ivc, v_sp_tdc
    P_theory_actual_exact = gas_exact.P
    T_theory_actual_exact = gas_exact.T

    # Full theoretical reference if full cylinder at 1 bar was compressed from BDC (CR=8.2)
    gas_ref = ct.Solution(MECH)
    gas_ref.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION
    gas_ref.SV = gas_ref.s, gas_ref.v / cr
    P_theory_full_charge = gas_ref.P

    ratio_sim_to_actual_theory = P_TDC_360 / P_theory_actual_exact

    # 8. Print Results
    print("\n" + "=" * 80)
    print("CYCLE MEASUREMENT RESULTS & PASS/FAIL VERIFICATION")
    print("=" * 80)

    print("\n1. Mass Flow & Trapping Accounting:")
    print(f"   - Initial Mass at 0° TDC:          {m_initial_TDC:.10e} kg ({m_initial_TDC * 1e3:.4f} g)")
    print(f"   - Total Intake Mass Induced:       {cum_m_in:.10e} kg ({cum_m_in * 1e3:.4f} g)")
    print(f"   - Total Exhaust Mass Expelled:     {cum_m_out:.10e} kg ({cum_m_out * 1e3:.4f} g)")
    print(f"   - Trapped Mass at IVC (228°):      {m_at_IVC:.10e} kg ({m_at_IVC * 1e3:.4f} g)")
    print(f"   - Mass at Compression TDC (360°):  {m_TDC_360:.10e} kg ({m_TDC_360 * 1e3:.4f} g)")
    print(f"   - Mass Conservation Error (228->360): {mass_conservation_error_compression_pct:.6e} %")

    print("\n2. Flow Rates & Peak Positions:")
    print(f"   - Peak Intake mdot:                {peak_mdot_in:.6e} kg/s at theta = {peak_mdot_in_theta:.1f}°")
    print(f"   - Peak Exhaust mdot:               {peak_mdot_out:.6e} kg/s at theta = {peak_mdot_out_theta:.1f}°")
    print(f"   - Exhaust Flow during Compression: {exhaust_flow_during_compression:.6e} kg")

    print("\n3. Pressure Results:")
    print(f"   - Pressure at IVC (228°):          {P_at_IVC / 1e5:.5f} bar ({P_at_IVC:.2f} Pa)")
    print(f"   - Simulated P at TDC (360°):       {P_TDC_360 / 1e5:.5f} bar ({P_TDC_360:.2f} Pa)")
    print(f"   - Peak Cylinder Pressure:          {P_peak / 1e5:.5f} bar at theta = {theta_peak_P:.1f}°")
    print(f"   - Min Cylinder Pressure:           {P_min / 1e5:.5f} bar at theta = {theta_min_P:.1f}°")

    print("\n4. Theoretical Pressure Comparison:")
    print(f"   - Effective Volume Ratio (IVC->TDC): {r_eff_IVC_to_TDC:.4f} (V_IVC={V_at_IVC*1e6:.2f} cc, V_TDC={V_TDC_360*1e6:.2f} cc)")
    print(f"   - Theoretical P (Actual Trapped Mass): {P_theory_actual_exact / 1e5:.5f} bar ({P_theory_actual_exact:.2f} Pa)")
    print(f"   - Const-gamma Theoretical P:          {P_theory_const_gamma / 1e5:.5f} bar")
    print(f"   - Simulated P / Theoretical P Ratio:  {ratio_sim_to_actual_theory:.6f} ({ratio_sim_to_actual_theory * 100.0:.2f} % agreement)")
    print(f"   - (Reference Full-Charge CR=8.2 P2):  {P_theory_full_charge / 1e5:.4f} bar")

    print("\n5. Temperature Results:")
    print(f"   - Temperature at IVC (228°):       {T_at_IVC:.2f} K")
    print(f"   - Simulated T at TDC (360°):       {T_TDC_360:.2f} K")
    print(f"   - Theoretical T (Actual Trapped):  {T_theory_actual_exact:.2f} K")

    print("\n6. Detailed Crank Angle Progression Trace:")
    print(f"  {'theta':>5} | {'V (cc)':>8} | {'P (bar)':>8} | {'T (K)':>7} | {'Mass (g)':>9} | {'Inlet':>6} | {'Outlet':>6} | {'mdot_in (kg/s)':>14} | {'mdot_out (kg/s)':>14} | {'Stroke'}")
    print("  " + "-" * 115)
    sample_angles = [0, 45, 90, 135, 180, 210, 228, 250, 280, 310, 340, 360, 400, 450, 492, 540, 600, 660, 720]
    for th in sample_angles:
        idx = thetas.index(float(th))
        stroke_name = ""
        if th < 180: stroke_name = "Intake"
        elif th < 228: stroke_name = "Intake (Late close)"
        elif th <= 360: stroke_name = "Compression (Sealed)"
        elif th < 492: stroke_name = "Expansion (Sealed)"
        elif th < 540: stroke_name = "Blowdown"
        else: stroke_name = "Exhaust push"
        print(f"  {th:5.1f} | {volumes[idx]*1e6:8.2f} | {pressures[idx]/1e5:8.4f} | {temperatures[idx]:7.2f} | {masses[idx]*1e3:9.5f} | {str(history['inlet_open'][idx]):>6} | {str(history['outlet_open'][idx]):>6} | {history['mdot_in'][idx]:14.4e} | {history['mdot_out'][idx]:14.4e} | {stroke_name}")

    # 9. Pass / Fail Evaluation
    pass_retention = abs(m_TDC_360 - m_at_IVC) / m_at_IVC < 1e-6
    pass_no_exhaust = exhaust_flow_during_compression < 1e-12
    pass_pressure_rise = P_TDC_360 > 10.0e5  # Must rise well above 1 bar
    pass_theory_match = abs(ratio_sim_to_actual_theory - 1.0) < 0.01  # Within 1% of exact isentropic theory
    pass_no_overlap = len(overlap_angles) == 0

    print("\n" + "=" * 80)
    print("PASS/FAIL CRITERIA CHECK")
    print("=" * 80)
    print(f"1. Zero Unintended Valve Overlap:      {'PASS' if pass_no_overlap else 'FAIL'}")
    print(f"2. Zero Exhaust Flow During Compression: {'PASS' if pass_no_exhaust else 'FAIL'} ({exhaust_flow_during_compression:.2e} kg)")
    print(f"3. Mass Conserved During Compression:    {'PASS' if pass_retention else 'FAIL'} (Error = {mass_conservation_error_compression_pct:.2e} %)")
    print(f"4. Pressure Rise above 10 bar:           {'PASS' if pass_pressure_rise else 'FAIL'} (P_TDC = {P_TDC_360/1e5:.4f} bar)")
    print(f"5. Agreement with Isentropic Theory (<1%): {'PASS' if pass_theory_match else 'FAIL'} ({ratio_sim_to_actual_theory*100:.2f}% of theory)")

    overall_pass = pass_retention and pass_no_exhaust and pass_pressure_rise and pass_theory_match and pass_no_overlap
    print(f"\nOVERALL RESULT: {'PASS' if overall_pass else 'FAIL'}")
    print("=" * 80)

    return {
        'overall_pass': overall_pass,
        'intake_window': (INTAKE_OPEN_DEG, INTAKE_CLOSE_DEG),
        'exhaust_window': (EXHAUST_OPEN_DEG, EXHAUST_CLOSE_DEG),
        'overlap_angles_count': len(overlap_angles),
        'm_initial_TDC': m_initial_TDC,
        'cum_m_in': cum_m_in,
        'cum_m_out': cum_m_out,
        'm_at_IVC': m_at_IVC,
        'm_TDC_360': m_TDC_360,
        'P_at_IVC': P_at_IVC,
        'P_TDC_360': P_TDC_360,
        'P_peak': P_peak,
        'theta_peak_P': theta_peak_P,
        'P_min': P_min,
        'theta_min_P': theta_min_P,
        'P_theory_actual_exact': P_theory_actual_exact,
        'ratio_sim_to_actual_theory': ratio_sim_to_actual_theory,
        'exhaust_flow_during_compression': exhaust_flow_during_compression,
    }


if __name__ == '__main__':
    res = run_corrected_timing_diagnostic()

