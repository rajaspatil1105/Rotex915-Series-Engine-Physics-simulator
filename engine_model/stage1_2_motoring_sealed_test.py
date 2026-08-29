"""
Motoring diagnostic with explicit sealed interval during compression (diagnostic-only).
- Inlet open window: 0°..120° absolute
- Outlet open window: 240°..360° absolute
This ensures a sealed interval from 120°..240°, which includes compression (180°..360° start).

This version uses a Cantera Wall (piston) between the cylinder reactor and a large remote reactor
so volume changes are handled by wall motion (preserves mass) instead of assigning reactor.volume directly.
"""
from math import pi, cos, radians, sin

ROTAX_GEOMETRY = {"bore_m":0.084, "stroke_m":0.061, "compression_ratio":8.2}
RPM = 3000
AMBIENT_P = 101325.0
AMBIENT_T = 288.15
MECH = 'gri30'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'
STEP_DEG = 1.0
N_CYCLES = 1

INLET_VALVE_COEFF_OPEN = 1e-3
OUTLET_VALVE_COEFF_OPEN = 1e-3
VALVE_COEFF_CLOSED = 0.0

from math import pi

def swept_volume_per_cylinder(bore_m, stroke_m):
    return (pi/4.0) * bore_m**2 * stroke_m

def clearance_volume_from_cr(vd, cr):
    return vd/(cr-1.0)

def cyl_volume_at_theta(vd, vc, theta_deg):
    theta_rad = radians(theta_deg)
    return vc + 0.5*vd*(1.0 - cos(theta_rad))

def dVdtheta(vd, theta_deg):
    # derivative dV/dtheta (m^3 per degree)
    theta_rad = radians(theta_deg)
    return 0.5 * vd * sin(theta_rad) * (pi / 180.0)

# explicit windows
INLET_OPEN = 0.0
INLET_CLOSE = 120.0
OUTLET_OPEN = 240.0
OUTLET_CLOSE = 360.0

def is_open_abs(theta_deg, open_deg, close_deg):
    theta = theta_deg % 720.0
    if close_deg >= open_deg:
        return (open_deg <= theta < close_deg)
    else:
        return (theta >= open_deg) or (theta < close_deg)


def run_sealed_test():
    import cantera as ct
    Vd = swept_volume_per_cylinder(ROTAX_GEOMETRY['bore_m'], ROTAX_GEOMETRY['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, ROTAX_GEOMETRY['compression_ratio'])
    Vmax = cyl_volume_at_theta(Vd, Vc, 180.0)
    Vmin = cyl_volume_at_theta(Vd, Vc, 0.0)

    print('\nRunning sealed-interval motoring diagnostic (diagnostic-only) — Wall-driven piston')
    print(f'INLET window {INLET_OPEN}..{INLET_CLOSE} deg; OUTLET window {OUTLET_OPEN}..{OUTLET_CLOSE} deg')

    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
    except Exception as e:
        print('Cantera error', e); raise
    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    try:
        try:
            cylinder = ct.IdealGasReactor(gas, clone=False)
        except TypeError:
            cylinder = ct.IdealGasReactor(gas)
    except Exception as e:
        print('reactor error', e); raise

    # create a large-volume remote reactor to act as a buffer/reservoir for the piston
    try:
        try:
            gas_res = ct.Solution(MECH + '.yaml')
        except Exception:
            gas_res = ct.Solution(MECH)
    except Exception:
        gas_res = gas
    gas_res.TP = AMBIENT_T, AMBIENT_P

    try:
        try:
            remote = ct.IdealGasReactor(gas_res, clone=False)
        except TypeError:
            remote = ct.IdealGasReactor(gas_res)
    except Exception as e:
        print('remote reactor error', e); raise

    # give remote a large volume so it approximates a reservoir
    remote.volume = 1.0  # 1 m^3

    # set initial cylinder volume at BDC so piston compresses toward Vmin
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    cylinder.volume = V_BDC

    # create wall (piston) between cylinder and remote reactor
    try:
        piston = ct.Wall(cylinder, remote)
    except Exception as e:
        print('ERROR: creating Wall:', type(e).__name__, str(e))
        raise

    # piston area
    piston_area = pi * (ROTAX_GEOMETRY['bore_m'] ** 2) / 4.0
    try:
        piston.area = piston_area
    except Exception:
        pass

    # inlet/outlet reservoirs and valves (unchanged)
    gas_inlet = ct.Solution(MECH + '.yaml') if True else None
    gas_inlet.TPX = AMBIENT_T, AMBIENT_P, 'O2:0.21, N2:0.79'
    inlet = ct.Reservoir(gas_inlet)
    inlet_valve = ct.Valve(inlet, cylinder)

    gas_outlet = ct.Solution(MECH + '.yaml')
    gas_outlet.TPX = AMBIENT_T, AMBIENT_P, 'O2:0.21, N2:0.79'
    outlet = ct.Reservoir(gas_outlet)
    outlet_valve = ct.Valve(cylinder, outlet)

    inlet_valve.time_function = (lambda t: True)
    outlet_valve.time_function = (lambda t: True)

    # ReactorNet includes both reactors so wall motion is integrated
    sim = ct.ReactorNet([cylinder, remote])

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    # tighten integrator step for consistent behavior with the analytic schedule
    try:
        sim.max_time_step = sec_per_deg / 100.0
    except Exception:
        pass

    steps_per_cycle = int(720.0 / STEP_DEG)

    # Align theta start with the initial cylinder.volume (initial volume set at BDC)
    start_theta = 180.0

    local_t = 0.0
    prev_V = cylinder.volume
    try:
        P_prev = cylinder.phase.P
    except Exception:
        P_prev = cylinder.thermo.P

    pressures=[]; temperatures=[]; volumes=[]; masses=[]; inlet_states=[]; outlet_states=[]
    expansion_work = 0.0; compression_work = 0.0; cycle_work = 0.0

    print('Cantera version:', ct.__version__)

    for s in range(0, steps_per_cycle):
        theta = start_theta + s * STEP_DEG
        # wrap theta within 0..720 for valve logic but allow theta>720 for motion continuity
        theta_mod = theta % 720.0
        V_target = cyl_volume_at_theta(Vd, Vc, theta)

        # valve coeffs based on crank angle (use wrapped theta)
        in_open = is_open_abs(theta_mod, INLET_OPEN, INLET_CLOSE)
        out_open = is_open_abs(theta_mod, OUTLET_OPEN, OUTLET_CLOSE)
        inlet_valve.valve_coeff = INLET_VALVE_COEFF_OPEN if in_open else VALVE_COEFF_CLOSED
        outlet_valve.valve_coeff = OUTLET_VALVE_COEFF_OPEN if out_open else VALVE_COEFF_CLOSED

        # compute piston velocity to achieve dV/dt matching desired schedule
        dV_dth = dVdtheta(Vd, theta)
        dV_dt = dV_dth * deg_per_sec
        velocity = dV_dt / piston_area

        # set piston velocity on wall if supported
        set_velocity_ok = False
        try:
            piston.velocity = velocity
            set_velocity_ok = True
        except Exception:
            try:
                piston.set_velocity(velocity)
                set_velocity_ok = True
            except Exception:
                set_velocity_ok = False

        dt = STEP_DEG * sec_per_deg
        local_t += dt
        try:
            sim.advance(local_t)
        except Exception as e:
            print('ERROR: ReactorNet advance failed at theta', theta, type(e).__name__, str(e))
            raise

        try:
            P_curr = cylinder.phase.P; T_curr = cylinder.phase.T; rho = cylinder.phase.density
        except Exception:
            P_curr = cylinder.thermo.P; T_curr = cylinder.thermo.T; rho = cylinder.thermo.density
        mass = rho * cylinder.volume
        dV = cylinder.volume - prev_V
        dW = 0.5 * (P_prev + P_curr) * dV
        cycle_work += dW
        if dV>0: expansion_work += dW
        else: compression_work += dW
        P_prev = P_curr; prev_V = cylinder.volume

        pressures.append(P_curr); temperatures.append(T_curr); volumes.append(cylinder.volume); masses.append(mass)
        inlet_states.append(in_open); outlet_states.append(out_open)

        if (s % 10 == 0) or (120.0 <= theta_mod <= 240.0):
            print(f"theta={theta_mod:.1f} deg, V={cylinder.volume*1e6:.6f} cc, P={P_curr:.6g} Pa, rho={rho:.6g} kg/m3, mass={mass:.12g} kg, piston_vel={velocity:.6g} m/s, set_vel_ok={set_velocity_ok}")

    initial_mass = masses[0]; final_mass = masses[-1]; min_mass=min(masses); max_mass=max(masses)
    total_in = 0.0; total_out = 0.0
    sealed_indices = [i for i,(a,b) in enumerate(zip(inlet_states,outlet_states)) if (not a) and (not b)]
    print('\nSealed indices count:', len(sealed_indices))
    if sealed_indices:
        print('Sealed window first/last theta:', (sealed_indices[0])*STEP_DEG + start_theta, (sealed_indices[-1])*STEP_DEG + start_theta)

    # find max pressure near Vmin
    Vmin_val = min(volumes)
    idx_minV = volumes.index(Vmin_val)

    print('\nResults:')
    print(f'  Vd = {Vd*1e6:.3f} cc, Vc = {Vc*1e6:.3f} cc, Vmax = {max(volumes)*1e6:.3f} cc, Vmin = {Vmin_val*1e6:.3f} cc')
    print(f'  initial_mass={initial_mass:.12e} kg, final_mass={final_mass:.12e} kg')
    print(f'  P_sim at minV = {pressures[idx_minV]:.6g} Pa ({pressures[idx_minV]/1e5:.6g} bar)')

    try:
        cp=gas.cp_mass; cv=gas.cv_mass; gamma=cp/cv
        P2 = AMBIENT_P * (V_BDC/Vmin_val)**gamma
        print(f'  gamma={gamma:.6g}, P2_theory={P2:.6g} Pa ({P2/1e5:.6g} bar)')
    except Exception:
        pass

    print('  net_work=', cycle_work)
    print('  expansion_work=', expansion_work, 'compression_work=', compression_work)

    print('\nSample around compression (every 10 deg):')
    for i in range(170,201,10):
        idx = (i - int(start_theta)) % len(volumes)
        print(f' {i:3d} deg: V={volumes[idx]*1e6:.3f} cc, P={pressures[idx]:.6g} Pa, inlet_open={inlet_states[idx]}, outlet_open={outlet_states[idx]}')

    return {
        'Vd_cc': Vd*1e6, 'Vc_cc':Vc*1e6, 'Vmax_cc':max(volumes)*1e6, 'Vmin_cc':Vmin_val*1e6,
        'initial_mass':initial_mass,'final_mass':final_mass,'P_sim_minV':pressures[idx_minV]
    }

if __name__=='__main__':
    res=run_sealed_test()
    print('\nNote: updated engine_model/stage1_2_motoring_sealed_test.py to Wall-driven piston (diagnostic).')