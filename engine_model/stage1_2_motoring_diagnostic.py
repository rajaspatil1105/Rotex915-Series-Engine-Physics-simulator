"""
Stage 1.2 motoring / cylinder-sealing diagnostic (diagnostic-only)
- Creates a separate diagnostic file only: engine_model/stage1_2_motoring_diagnostic.py
- Do not modify any existing project files.

Per user instructions: combustion and ignition OFF; 1 cycle (720 deg); STEP_DEG=1°; record detailed state.
"""
from math import pi, cos, radians

# ---------------------------------------------------------------------------
# Geometry & Phase-0 (copied from gas-exchange diagnostic)
# ---------------------------------------------------------------------------
ROTAX_GEOMETRY = {
    "cylinders": 4,
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "displacement_per_cylinder_m3": 0.000338,
    "compression_ratio": 8.2,
}

PHASE0 = {
    "intake_open_deg_TDC": 0.0,
    "intake_close_deg_ABDC": 48.0,
    "exhaust_open_deg_BBDC": 48.0,
    "exhaust_close_deg_TDC": 0.0,
    "ignition_timing_deg_BTDC": 20.0,
}

# Operating
RPM = 3000
AMBIENT_P = 101325.0
AMBIENT_T = 288.15
MECH = 'gri30'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'
STEP_DEG = 1.0
N_CYCLES = 1

# Valve coefficients for open state (diagnostic)
INLET_VALVE_COEFF_OPEN = 1.e-3
OUTLET_VALVE_COEFF_OPEN = 1.e-3
# Closed coefficient must be exactly 0.0
VALVE_COEFF_CLOSED = 0.0

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))

# ---------------------------------------------------------------------------
# Motoring diagnostic
# ---------------------------------------------------------------------------

def run_motoring(step_deg: float = STEP_DEG):
    import cantera as ct

    # prepare geometry
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])
    Vmax = cyl_volume_at_theta(Vd, Vc, 180.0)  # at BDC
    Vmin = cyl_volume_at_theta(Vd, Vc, 0.0)    # at TDC

    # print geometry checks
    print('\nGeometry check:')
    print(f'  Vd (m^3) = {Vd:.6e} m^3  ({Vd*1e6:.3f} cc)')
    print(f'  Vc (m^3) = {Vc:.6e} m^3  ({Vc*1e6:.3f} cc)')
    print(f'  Vmax (m^3) = {Vmax:.6e} m^3  ({Vmax*1e6:.3f} cc)')
    print(f'  Vmin (m^3) = {Vmin:.6e} m^3  ({Vmin*1e6:.3f} cc)')
    print(f'  Vmax/Vmin = {Vmax/Vmin:.6g}')
    eff_cr = Vmax / Vmin
    print(f'  effective CR = {eff_cr:.6g}')

    # check expected approx values
    print('\nExpected (approx):')
    print('  Vd ~ 338 cc, Vc ~ 46.95 cc, Vmax ~ 384.95 cc, Vmin ~ 46.95 cc, CR ~ 8.2')

    # validate mechanism
    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
    except Exception as e:
        print('ERROR creating mechanism:', e)
        raise

    # initial gas state
    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    # compute gamma from cp and cv if available
    try:
        cp = gas.cp_mass
        cv = gas.cv_mass
        gamma = cp / cv if (cv and cv > 0) else None
    except Exception:
        gamma = None

    print('\nInitial thermodynamic state:')
    print(f'  P1 = {gas.P:.6g} Pa')
    print(f'  T1 = {gas.T:.6g} K')
    if gamma:
        print(f'  gamma (cp/cv) = {gamma:.6g}')

    # theoretical isentropic compression from V1 (Vmax) to V2 (Vmin)
    P1 = gas.P
    V1 = Vmax
    V2 = Vmin
    if gamma:
        P2_theory = P1 * (V1 / V2) ** gamma
        print('\nTheoretical isentropic compression:')
        print(f'  V1 = {V1*1e6:.6f} cc, V2 = {V2*1e6:.6f} cc')
        print(f'  P2_theory = {P2_theory:.6g} Pa  ({P2_theory/1e5:.6g} bar)')
    else:
        P2_theory = None
        print('  gamma not available, cannot compute theoretical P2')

    # valve timing (absolute crank degrees 0..720)
    intake_open_deg = PHASE0['intake_open_deg_TDC']
    intake_close_deg = 180.0 + PHASE0['intake_close_deg_ABDC']
    exhaust_open_deg = 180.0 - PHASE0['exhaust_open_deg_BBDC']
    exhaust_close_deg = PHASE0['exhaust_close_deg_TDC']

    def deg_to_rad(d):
        return d / 180.0 * pi

    inlet_open_rad = deg_to_rad(intake_open_deg)
    inlet_close_rad = deg_to_rad(intake_close_deg)
    outlet_open_rad = deg_to_rad(exhaust_open_deg)
    outlet_close_rad = deg_to_rad(exhaust_close_deg)

    f = RPM / 60.0

    def crank_angle(t):
        return float((2.0 * pi * f * t) % (4.0 * pi))

    def crank_angle_deg(t):
        return (360.0 * f * t) % 720.0

    # helper to determine if angle is within open window
    def is_open(theta_deg, open_deg, close_deg):
        # treat wrap-around across 720->0
        theta = theta_deg % 720.0
        if close_deg >= open_deg:
            return (open_deg <= theta < close_deg)
        else:
            # wraps
            return (theta >= open_deg) or (theta < close_deg)

    # verify valve states programmatically at requested angles before run
    check_angles = [0,30,90,180,228,270,360,400,480,540,600,700,719]
    print('\nValve state verification at representative angles (before run):')
    for a in check_angles:
        in_open = is_open(a, intake_open_deg, intake_close_deg)
        out_open = is_open(a, exhaust_open_deg, exhaust_close_deg)
        coeff_in = INLET_VALVE_COEFF_OPEN if in_open else VALVE_COEFF_CLOSED
        coeff_out = OUTLET_VALVE_COEFF_OPEN if out_open else VALVE_COEFF_CLOSED
        print(f'  {a:3d}°: inlet_open={in_open}, inlet_coeff={coeff_in}, outlet_open={out_open}, outlet_coeff={coeff_out}')

    # create reactor
    try:
        try:
            reactor = ct.IdealGasReactor(gas, clone=False)
        except TypeError:
            reactor = ct.IdealGasReactor(gas)
    except Exception as e:
        print('ERROR creating reactor:', e)
        raise

    reactor.volume = cyl_volume_at_theta(Vd, Vc, 0.0)

    # reservoirs
    try:
        try:
            gas_inlet = ct.Solution(MECH + '.yaml')
        except Exception:
            gas_inlet = ct.Solution(MECH)
    except Exception:
        gas_inlet = None
    if gas_inlet is not None:
        gas_inlet.TPX = AMBIENT_T, AMBIENT_P, 'O2:0.21, N2:0.79'
        inlet = ct.Reservoir(gas_inlet)
    else:
        inlet = None

    try:
        try:
            gas_outlet = ct.Solution(MECH + '.yaml')
        except Exception:
            gas_outlet = ct.Solution(MECH)
    except Exception:
        gas_outlet = None
    if gas_outlet is not None:
        gas_outlet.TPX = AMBIENT_T, AMBIENT_P, 'O2:0.21, N2:0.79'
        outlet = ct.Reservoir(gas_outlet)
    else:
        outlet = None

    # create valves; we'll control valve_coeff explicitly each step so closed coeff is exactly 0.0
    inlet_valve = ct.Valve(inlet, reactor) if inlet is not None else None
    outlet_valve = ct.Valve(reactor, outlet) if outlet is not None else None

    # set a neutral time function (always True) because we'll set valve_coeff per-step exactly
    if inlet_valve is not None:
        inlet_valve.time_function = (lambda t: True)
    if outlet_valve is not None:
        outlet_valve.time_function = (lambda t: True)

    sim = ct.ReactorNet([reactor])

    # integration initializations
    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / step_deg)
    local_t = 0.0
    prev_V = reactor.volume
    P_prev = reactor.thermo.P

    pressures = []
    temperatures = []
    volumes = []
    masses = []
    inlet_states = []
    outlet_states = []

    expansion_work = 0.0
    compression_work = 0.0
    cycle_work = 0.0

    for s in range(1, steps_per_cycle + 1):
        theta = s * step_deg
        V_new = cyl_volume_at_theta(Vd, Vc, theta)
        dV = V_new - prev_V
        reactor.volume = V_new

        # set valve coefficients exactly according to open windows
        in_open = is_open(theta, intake_open_deg, intake_close_deg)
        out_open = is_open(theta, exhaust_open_deg, exhaust_close_deg)
        if inlet_valve is not None:
            inlet_valve.valve_coeff = INLET_VALVE_COEFF_OPEN if in_open else VALVE_COEFF_CLOSED
        if outlet_valve is not None:
            outlet_valve.valve_coeff = OUTLET_VALVE_COEFF_OPEN if out_open else VALVE_COEFF_CLOSED

        dt = step_deg * sec_per_deg
        local_t += dt
        # advance integrator to this time
        try:
            sim.advance(local_t)
        except Exception as e:
            print('ERROR: ReactorNet advance failed at theta', theta, type(e).__name__, e)
            raise

        # read state
        P_curr = reactor.thermo.P
        T_curr = reactor.thermo.T
        rho = reactor.thermo.density
        mass = rho * reactor.volume

        # trapezoidal work
        dW = 0.5 * (P_prev + P_curr) * dV
        cycle_work += dW
        if dV > 0:
            expansion_work += dW
        else:
            compression_work += dW

        P_prev = P_curr
        prev_V = V_new

        pressures.append(P_curr)
        temperatures.append(T_curr)
        volumes.append(V_new)
        masses.append(mass)
        inlet_states.append(in_open)
        outlet_states.append(out_open)

    # after cycle
    initial_mass = masses[0]
    final_mass = masses[-1]
    min_mass = min(masses)
    max_mass = max(masses)
    abs_mass_change = final_mass - initial_mass
    pct_mass_change = (abs_mass_change / initial_mass * 100.0) if initial_mass else None

    # find max pressure near min volume (search near theta where V==Vmin)
    idx_minV = min(range(len(volumes)), key=lambda i: abs(volumes[i] - Vmin))
    theta_minV = (idx_minV + 1) * step_deg
    P_sim_max = pressures[idx_minV]

    # theoretical P2 computed earlier (P2_theory)

    # mass change while sealed: determine indices where both valves closed
    sealed_indices = [i for i,(in_s,out_s) in enumerate(zip(inlet_states, outlet_states)) if (not in_s) and (not out_s)]
    mass_during_sealed = [masses[i] for i in sealed_indices] if sealed_indices else []
    mass_change_sealed = None
    pct_change_sealed = None
    sealed_flag = False
    if mass_during_sealed:
        mass_change_sealed = mass_during_sealed[-1] - mass_during_sealed[0]
        pct_change_sealed = (mass_change_sealed / mass_during_sealed[0] * 100.0) if mass_during_sealed[0] else None
        # set flag if absolute or percent change significant (tolerance: absolute >1e-8 kg or pct>0.001%)
        if abs(mass_change_sealed) > 1e-8 or (pct_change_sealed is not None and abs(pct_change_sealed) > 0.001):
            sealed_flag = True

    # P-V work totals
    net_work = cycle_work

    # print summary report
    print('\nMotoring diagnostic summary:')
    print(f'  initial_mass = {initial_mass:.12e} kg')
    print(f'  min_mass = {min_mass:.12e} kg')
    print(f'  max_mass = {max_mass:.12e} kg')
    print(f'  final_mass = {final_mass:.12e} kg')
    print(f'  abs_mass_change = {abs_mass_change:.12e} kg')
    if pct_mass_change is not None:
        print(f'  pct_mass_change = {pct_mass_change:.6g} %')

    print('\nValve sealing verification (sampled states):')
    sample_angles = [0,30,90,180,228,270,360,400,480,540,600,700,719]
    for a in sample_angles:
        idx = int(a / step_deg) - 1
        if idx < 0:
            idx = 0
        in_s = inlet_states[idx]
        out_s = outlet_states[idx]
        coeff_in = INLET_VALVE_COEFF_OPEN if in_s else VALVE_COEFF_CLOSED
        coeff_out = OUTLET_VALVE_COEFF_OPEN if out_s else VALVE_COEFF_CLOSED
        print(f'  {a:3d}°: inlet_open={in_s}, inlet_coeff={coeff_in}, outlet_open={out_s}, outlet_coeff={coeff_out}')

    print('\nCompression check:')
    print(f'  simulated max pressure near Vmin at theta={theta_minV} deg: P_sim = {P_sim_max:.6g} Pa ({P_sim_max/1e5:.6g} bar)')
    if P2_theory is not None:
        print(f'  theoretical P2 = {P2_theory:.6g} Pa ({P2_theory/1e5:.6g} bar)')
        ratio = (P_sim_max / P2_theory) if P2_theory else None
        pct_diff = ((P_sim_max - P2_theory) / P2_theory * 100.0) if P2_theory else None
        print(f'  simulated/theoretical = {ratio:.6g}')
        print(f'  percentage difference = {pct_diff:.6g} %')

    print('\nSealed-mass-change during sealed portion:')
    if mass_change_sealed is not None:
        print(f'  mass_change_sealed = {mass_change_sealed:.12e} kg')
        print(f'  pct_change_sealed = {pct_change_sealed:.6g} %')
    else:
        print('  no sealed interval detected (valves open continuously)')

    print('\nP-V work:')
    print(f'  expansion_work = {expansion_work:.6g} J')
    print(f'  compression_work = {compression_work:.6g} J')
    print(f'  net_work = {net_work:.6g} J')

    # print representative data every 10° and around TDC/BDC
    print('\nRepresentative time history (every 10°):')
    n = len(pressures)
    for i in range(0, n, int(10/step_deg)):
        theta = (i+1) * step_deg
        print(f'  {theta:6.1f} deg: V={volumes[i]*1e6:.3f} cc, P={pressures[i]:.6g} Pa ({pressures[i]/1e5:.6g} bar), T={temperatures[i]:.6g} K, mass={masses[i]:.12e} kg, inlet_open={inlet_states[i]}, outlet_open={outlet_states[i]}')

    # around TDC / BDC neighborhood
    print('\nValues near TDC (0 deg):')
    for a in [-3,-2,-1,0,1,2,3]:
        theta = (a % 720)
        idx = int(theta / step_deg)
        print(f'  {theta:4.0f} deg: P={pressures[idx]:.6g} Pa, V={volumes[idx]*1e6:.6f} cc, mass={masses[idx]:.12e} kg')

    print('\nValues near BDC (180 deg):')
    for a in [177,178,179,180,181,182,183]:
        idx = int(a / step_deg) - 1
        if idx < 0:
            idx = 0
        print(f'  {a:4.0f} deg: P={pressures[idx]:.6g} Pa, V={volumes[idx]*1e6:.6f} cc, mass={masses[idx]:.12e} kg')

    # classification
    print('\nFinal classification:')
    # Criteria checks
    pass_geometry = abs((Vd*1e6) - 338.0) < 5.0  # within 5 cc
    pass_vmin = abs((Vmin*1e6) - 46.95) < 2.0
    valves_closed_during_sealed = True if sealed_indices else False
    mass_constant_sealed = not sealed_flag
    compression_reasonable = False
    if P2_theory is not None:
        if P2_theory > 0:
            pct_diff_abs = abs((P_sim_max - P2_theory) / P2_theory * 100.0)
            compression_reasonable = pct_diff_abs < 50.0  # within 50% considered reasonable for motoring
    # decide
    if pass_geometry and pass_vmin and valves_closed_during_sealed and mass_constant_sealed and compression_reasonable:
        classification = 'PASS'
        recommendation = 'Proceed to fixing/modeling the dynamic gas-exchange system.'
    else:
        classification = 'FAIL' if (not mass_constant_sealed or not valves_closed_during_sealed or not pass_vmin or not compression_reasonable) else 'INCONCLUSIVE'
        recommendation = 'Investigate valve sealing or geometry discrepancies before proceeding.'

    print(f'  CLASSIFICATION = {classification}')
    print(f'  RECOMMENDATION: {recommendation}')

    return {
        'Vd_m3': Vd,
        'Vc_m3': Vc,
        'Vmax_m3': Vmax,
        'Vmin_m3': Vmin,
        'effective_CR': eff_cr,
        'P2_theory_Pa': P2_theory,
        'P_sim_max_Pa': P_sim_max,
        'classification': classification,
        'recommendation': recommendation,
    }


if __name__ == '__main__':
    print('Running Stage 1.2 motoring/cylinder-sealing diagnostic (diagnostic-only)')
    import cantera as ct
    print('Cantera version:', ct.__version__)
    res = run_motoring()
    print('\nNote: Only engine_model\stage1_2_motoring_diagnostic.py was created. No existing files were changed.')