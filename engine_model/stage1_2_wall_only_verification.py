"""
Stage 1.2: Wall-only Isolated Compression Verification (diagnostic-only)

Purpose:
Completely isolated compression test using a Cantera Wall-driven piston:
- One IdealGasReactor (cylinder)
- One Cantera Wall/piston
- One large remote IdealGasReactor acting as passive volume buffer
- NO valves
- NO reservoirs
- NO combustion / spark
- Initialize at BDC (theta = 180 deg, V = Vmax)
- Compress to TDC (theta = 360 deg, V = Vmin)
- Single 720-deg cycle motoring kinematics
- Use official Rotax 915 iS geometry and Phase-0 baseline conditions

Metrics measured:
- Vmax, Vmin, Displacement Vd, Clearance Vc, Compression Ratio CR
- Initial mass, final mass, max mass deviation, mass conservation error (%)
- P1, T1 at BDC; P2, T2 at TDC
- Theoretical isentropic P2 (constant gamma and exact Cantera variable-cp isentropic)
- Simulated P2
- Simulated / Theoretical ratio
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
STEP_DEG = 1.0  # crank-angle step in degrees


def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * (bore_m ** 2) * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    # theta = 0 deg -> TDC (V = Vc)
    # theta = 180 deg -> BDC (V = Vc + Vd)
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


def dVdtheta(vd: float, theta_deg: float) -> float:
    # dV/dtheta in m^3 / degree
    theta_rad = radians(theta_deg)
    return 0.5 * vd * sin(theta_rad) * (pi / 180.0)


def run_wall_only_verification():
    import cantera as ct

    print("=" * 70)
    print("STAGE 1.2: WALL-ONLY ISOLATED COMPRESSION VERIFICATION")
    print(f"Cantera Version: {ct.__version__}")
    print("=" * 70)

    # 1. Geometry Calculations
    g = ROTAX_GEOMETRY
    bore = g['bore_m']
    stroke = g['stroke_m']
    cr_target = g['compression_ratio']

    Vd = swept_volume_per_cylinder(bore, stroke)
    Vc = clearance_volume_from_cr(Vd, cr_target)
    V_TDC = cyl_volume_at_theta(Vd, Vc, 0.0)
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    piston_area = (pi / 4.0) * (bore ** 2)
    CR_calc = V_BDC / V_TDC

    print("\n--- 1. GEOMETRY SANITY CHECKS ---")
    print(f"Bore:               {bore * 1000.0:.3f} mm")
    print(f"Stroke:             {stroke * 1000.0:.3f} mm")
    print(f"Piston Area:        {piston_area * 1e4:.4f} cm^2 ({piston_area:.6e} m^2)")
    print(f"Displacement (Vd):  {Vd * 1e6:.6f} cc ({Vd:.8e} m^3)")
    print(f"Clearance (Vc):     {Vc * 1e6:.6f} cc ({Vc:.8e} m^3)")
    print(f"V_max (at BDC):     {V_BDC * 1e6:.6f} cc ({V_BDC:.8e} m^3)")
    print(f"V_min (at TDC):     {V_TDC * 1e6:.6f} cc ({V_TDC:.8e} m^3)")
    print(f"Compression Ratio:  {CR_calc:.4f}")

    # 2. Setup Gas and Theoretical Isentropic State
    try:
        gas = ct.Solution(MECH)
    except Exception:
        gas = ct.Solution('gri30')

    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION
    P1 = gas.P
    T1 = gas.T
    rho1 = gas.density
    cp1 = gas.cp_mass
    cv1 = gas.cv_mass
    gamma1 = cp1 / cv1
    s1 = gas.s
    v1_sp = gas.v  # specific volume m^3/kg

    # Theoretical constant-gamma isentropic calculation
    P2_const_gamma = P1 * (CR_calc ** gamma1)
    T2_const_gamma = T1 * (CR_calc ** (gamma1 - 1.0))

    # Theoretical exact variable-cp isentropic calculation via Cantera Thermo
    gas_exact = ct.Solution(MECH)
    gas_exact.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION
    gas_exact.SV = s1, v1_sp / CR_calc
    P2_exact_isentropic = gas_exact.P
    T2_exact_isentropic = gas_exact.T

    print("\n--- 2. INITIAL THERMODYNAMIC STATE & THEORETICAL ISENTROPIC TARGETS ---")
    print(f"Initial Composition: {FUEL_COMPOSITION}")
    print(f"Initial P1:          {P1:.2f} Pa ({P1 / 1e5:.5f} bar)")
    print(f"Initial T1:          {T1:.2f} K")
    print(f"Initial Density:     {rho1:.6f} kg/m^3")
    print(f"gamma (cp/cv at T1): {gamma1:.4f}")
    print(f"Theoretical P2 (const-gamma={gamma1:.4f}): {P2_const_gamma:.2f} Pa ({P2_const_gamma / 1e5:.4f} bar)")
    print(f"Theoretical T2 (const-gamma):              {T2_const_gamma:.2f} K")
    print(f"Theoretical P2 (exact variable-cp isentropic): {P2_exact_isentropic:.2f} Pa ({P2_exact_isentropic / 1e5:.4f} bar)")
    print(f"Theoretical T2 (exact variable-cp isentropic): {T2_exact_isentropic:.2f} K")

    # 3. Create Cantera Reactor and Wall
    cylinder = ct.IdealGasReactor(gas, clone=False)
    cylinder.volume = V_BDC

    # Passive remote buffer reactor (large volume, no mass exchange)
    gas_remote = ct.Solution(MECH)
    gas_remote.TP = AMBIENT_T, AMBIENT_P
    remote = ct.IdealGasReactor(gas_remote, clone=False)
    remote.volume = 1.0  # 1 m^3

    # Piston Wall connecting cylinder and remote reactor
    piston = ct.Wall(cylinder, remote)
    piston.area = piston_area

    sim = ct.ReactorNet([cylinder, remote])

    deg_per_sec = RPM * 360.0 / 60.0  # deg/s
    sec_per_deg = 1.0 / deg_per_sec
    dt = STEP_DEG * sec_per_deg

    # Tighten integrator max timestep for high fidelity
    try:
        sim.max_time_step = sec_per_deg / 50.0
    except Exception:
        pass

    # 4. Run Isolated Compression Cycle
    # We initialize at BDC (theta = 180 deg) and move through compression to TDC (theta = 360 deg),
    # followed by expansion back to BDC (540 deg) and second compression to TDC (720 deg).
    total_steps = int(720.0 / STEP_DEG)
    start_theta = 180.0

    history = {
        'theta': [],
        'volume': [],
        'pressure': [],
        'temperature': [],
        'density': [],
        'mass': [],
        'velocity': [],
    }

    local_t = 0.0
    initial_mass = cylinder.phase.density * cylinder.volume

    print("\n--- 3. SIMULATION EXECUTION (BDC theta=180 -> TDC theta=360 -> BDC theta=540 -> TDC theta=720) ---")

    for s in range(total_steps + 1):
        theta = start_theta + s * STEP_DEG

        # Measure current state
        rho = cylinder.phase.density
        vol = cylinder.volume
        P = cylinder.phase.P
        T = cylinder.phase.T
        mass = rho * vol

        history['theta'].append(theta)
        history['volume'].append(vol)
        history['pressure'].append(P)
        history['temperature'].append(T)
        history['density'].append(rho)
        history['mass'].append(mass)

        if s == total_steps:
            break

        # Compute exact velocity to achieve target discrete volume change over dt:
        # delta_V = V(theta + STEP_DEG) - V(theta)
        # velocity = (delta_V / dt) / piston_area
        V_next = cyl_volume_at_theta(Vd, Vc, theta + STEP_DEG)
        V_curr = cyl_volume_at_theta(Vd, Vc, theta)
        delta_V = V_next - V_curr
        vel = (delta_V / dt) / piston_area
        history['velocity'].append(vel)

        piston.velocity = vel

        local_t += dt
        sim.advance(local_t)

    # 5. Extract Key Metrics
    volumes_cc = [v * 1e6 for v in history['volume']]
    pressures_bar = [p / 1e5 for p in history['pressure']]
    temperatures_K = history['temperature']
    masses_kg = history['mass']
    thetas = history['theta']

    # Initial BDC state
    idx_bdc_start = 0
    # First TDC state (at theta = 360 deg)
    idx_tdc_1 = thetas.index(360.0)
    # Second BDC state (at theta = 540 deg)
    idx_bdc_2 = thetas.index(540.0)
    # Second TDC state (at theta = 720 deg)
    idx_tdc_2 = thetas.index(720.0)

    P_TDC_1 = history['pressure'][idx_tdc_1]
    T_TDC_1 = history['temperature'][idx_tdc_1]
    V_TDC_1 = history['volume'][idx_tdc_1]

    V_min_sim = min(history['volume'])
    V_max_sim = max(history['volume'])
    CR_sim = V_max_sim / V_min_sim

    mass_initial = masses_kg[0]
    mass_final = masses_kg[-1]
    mass_min = min(masses_kg)
    mass_max = max(masses_kg)
    max_mass_deviation = max(abs(m - mass_initial) for m in masses_kg)
    mass_conservation_error_pct = (max_mass_deviation / mass_initial) * 100.0

    ratio_sim_to_exact = P_TDC_1 / P2_exact_isentropic
    ratio_sim_to_const_gamma = P_TDC_1 / P2_const_gamma

    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)
    print(f"1. Volume Metrics:")
    print(f"   - Vmax (Simulated):       {V_max_sim * 1e6:.6f} cc (Target: {V_BDC * 1e6:.6f} cc)")
    print(f"   - Vmin (Simulated):       {V_min_sim * 1e6:.6f} cc (Target: {V_TDC * 1e6:.6f} cc)")
    print(f"   - Compression Ratio (CR): {CR_sim:.6f} (Target: {cr_target:.4f})")
    print(f"   - Volume Kinematic Error: {abs(CR_sim - cr_target) / cr_target * 100.0:.6e} %")

    print(f"\n2. Mass Conservation Metrics:")
    print(f"   - Initial Mass (at BDC):  {mass_initial:.12e} kg")
    print(f"   - Final Mass (after 720°): {mass_final:.12e} kg")
    print(f"   - Min Mass during test:   {mass_min:.12e} kg")
    print(f"   - Max Mass during test:   {mass_max:.12e} kg")
    print(f"   - Max Mass Deviation:     {max_mass_deviation:.12e} kg")
    print(f"   - Mass Error (%):         {mass_conservation_error_pct:.6e} %")

    print(f"\n3. Pressure & Compression Metrics:")
    print(f"   - Initial P1 (at BDC):    {P1 / 1e5:.5f} bar ({P1:.2f} Pa)")
    print(f"   - Simulated P2 (at TDC):  {P_TDC_1 / 1e5:.5f} bar ({P_TDC_1:.2f} Pa)")
    print(f"   - Exact Isentropic P2:    {P2_exact_isentropic / 1e5:.5f} bar ({P2_exact_isentropic:.2f} Pa)")
    print(f"   - Const-gamma P2:         {P2_const_gamma / 1e5:.5f} bar ({P2_const_gamma:.2f} Pa)")
    print(f"   - Sim / Exact Theory:     {ratio_sim_to_exact:.6f} (Agreement: {ratio_sim_to_exact * 100.0:.4f} %)")
    print(f"   - Sim / Const-gamma:      {ratio_sim_to_const_gamma:.6f}")

    print(f"\n4. Temperature Metrics:")
    print(f"   - Initial T1 (at BDC):    {T1:.2f} K")
    print(f"   - Simulated T2 (at TDC):  {T_TDC_1:.2f} K")
    print(f"   - Exact Isentropic T2:    {T2_exact_isentropic:.2f} K")
    print(f"   - Const-gamma T2:         {T2_const_gamma:.2f} K")

    print("\n5. Crank Angle Profile Progression:")
    for th in [180.0, 225.0, 270.0, 315.0, 360.0, 405.0, 450.0, 495.0, 540.0, 630.0, 720.0]:
        idx = thetas.index(th)
        print(f"   theta = {th:5.1f}° | V = {volumes_cc[idx]:8.3f} cc | P = {pressures_bar[idx]:8.4f} bar | T = {temperatures_K[idx]:7.2f} K | mass = {masses_kg[idx]:.10e} kg")

    # Pass/Fail Criteria Evaluation
    cr_pass = abs(CR_sim - cr_target) < 1e-2  # Within 0.01 of 8.2
    mass_pass = mass_conservation_error_pct < 1e-6
    pressure_pass = (18.0 <= (P_TDC_1 / 1e5) <= 20.0) and (abs(ratio_sim_to_exact - 1.0) < 0.01)

    print("\n" + "=" * 70)
    print("PASS/FAIL VERIFICATION")
    print("=" * 70)
    print(f"CR Match (CR = 8.2):                  {'PASS' if cr_pass else 'FAIL'} (CR = {CR_sim:.6f})")
    print(f"Mass Conservation (<1e-6 %):          {'PASS' if mass_pass else 'FAIL'} (Error = {mass_conservation_error_pct:.6e} %)")
    print(f"Compression Pressure (~19 bar, ~100%): {'PASS' if pressure_pass else 'FAIL'} (P_TDC = {P_TDC_1 / 1e5:.4f} bar, {ratio_sim_to_exact*100:.2f}% of theory)")

    overall_pass = cr_pass and mass_pass and pressure_pass
    print(f"\nOVERALL RESULT: {'PASS' if overall_pass else 'FAIL'}")
    print("=" * 70)

    return {
        'overall_pass': overall_pass,
        'CR_calc': CR_calc,
        'CR_sim': CR_sim,
        'V_max_cc': V_max_sim * 1e6,
        'V_min_cc': V_min_sim * 1e6,
        'mass_initial': mass_initial,
        'mass_final': mass_final,
        'max_mass_deviation': max_mass_deviation,
        'mass_conservation_error_pct': mass_conservation_error_pct,
        'P1_Pa': P1,
        'P1_bar': P1 / 1e5,
        'P_TDC_Pa': P_TDC_1,
        'P_TDC_bar': P_TDC_1 / 1e5,
        'P2_exact_Pa': P2_exact_isentropic,
        'P2_exact_bar': P2_exact_isentropic / 1e5,
        'P2_const_gamma_bar': P2_const_gamma / 1e5,
        'ratio_sim_to_exact': ratio_sim_to_exact,
        'T1_K': T1,
        'T_TDC_K': T_TDC_1,
        'T2_exact_K': T2_exact_isentropic,
    }


if __name__ == '__main__':
    run_wall_only_verification()
