"""
Closed-reactor piston-driven compression test (diagnostic-only)
- One IdealGasReactor (cylinder) connected to another IdealGasReactor by a ct.Wall (piston)
- No valves, no reservoirs (no mass exchange)
- Geometry and V(theta) function taken exactly from stage1_2_na_baseline.py
- Initialize at BDC and compress to TDC, one 720-degree cycle at STEP_DEG=1
- Reports Vmax/Vmin, effective CR, mass conservation, simulated P at TDC, theoretical P2
"""
from math import pi, cos, radians, sin

# geometry (exact)
ROTAX_GEOMETRY = {"bore_m":0.084, "stroke_m":0.061, "compression_ratio":8.2}
RPM = 3000
AMBIENT_P = 101325.0
AMBIENT_T = 288.15
MECH = 'gri30'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'
STEP_DEG = 1.0

def swept_volume_per_cylinder(bore_m, stroke_m):
    return (pi/4.0) * bore_m**2 * stroke_m

def clearance_volume_from_cr(vd, cr):
    return vd/(cr-1.0)

def cyl_volume_at_theta(vd, vc, theta_deg):
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))

def dVdtheta(vd, theta_deg):
    theta_rad = radians(theta_deg)
    return 0.5 * vd * sin(theta_rad) * (pi/180.0)


def run_closed_wall_test():
    import cantera as ct
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])
    V_TDC = cyl_volume_at_theta(Vd, Vc, 0.0)
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)

    print('\nClosed-reactor Wall compression verification')
    print(f'Vd={Vd*1e6:.6f} cc, Vc={Vc*1e6:.6f} cc, V_BDC={V_BDC*1e6:.6f} cc, V_TDC={V_TDC*1e6:.6f} cc')

    # prepare gas
    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
    except Exception as e:
        print('Cantera error creating mechanism:', e); raise
    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    # create cylinder reactor
    try:
        try:
            cylinder = ct.IdealGasReactor(gas, clone=False)
        except TypeError:
            cylinder = ct.IdealGasReactor(gas)
    except Exception as e:
        print('Error creating cylinder reactor:', e); raise

    # create remote reactor (no reservoirs) as buffer
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
        print('Error creating remote reactor:', e); raise

    # remote large volume
    remote.volume = 1.0

    # initial cylinder volume at BDC
    cylinder.volume = V_BDC

    # connect wall
    try:
        piston = ct.Wall(cylinder, remote)
    except Exception as e:
        print('Error creating Wall:', e); raise

    piston_area = pi * (g['bore_m'] ** 2) / 4.0
    try:
        piston.area = piston_area
    except Exception:
        pass

    sim = ct.ReactorNet([cylinder, remote])

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    # limit internal integrator timestep to improve accuracy (smaller than one crank degree)
    try:
        # tighten integrator step to improve numerical fidelity
        sim.max_time_step = sec_per_deg / 100.0
    except Exception:
        # older Cantera may use different property; ignore if unavailable
        pass

    steps_per_cycle = int(720.0 / STEP_DEG)

    masses = []
    volumes = []
    pressures = []

    local_t = 0.0

    # initial state
    try:
        P_prev = cylinder.phase.P
    except Exception:
        P_prev = cylinder.thermo.P

    # Start at BDC (theta=180 deg) so initial cylinder.volume matches the theta schedule.
    start_theta = 180.0
    for s in range(0, steps_per_cycle):
        theta = start_theta + s * STEP_DEG
        # compute piston velocity to match dV/dt (theta in degrees, accepts any real theta)
        dV_dth = dVdtheta(Vd, theta)
        dV_dt = dV_dth * deg_per_sec
        velocity = dV_dt / piston_area

        # set velocity
        try:
            piston.velocity = velocity
            set_vel_ok = True
        except Exception:
            try:
                piston.set_velocity(velocity)
                set_vel_ok = True
            except Exception:
                set_vel_ok = False

        # advance
        dt = STEP_DEG / deg_per_sec
        local_t += dt
        sim.advance(local_t)

        # read states
        try:
            P = cylinder.phase.P; T = cylinder.phase.T; rho = cylinder.phase.density
        except Exception:
            P = cylinder.thermo.P; T = cylinder.thermo.T; rho = cylinder.thermo.density
        mass = rho * cylinder.volume

        masses.append(mass)
        volumes.append(cylinder.volume)
        pressures.append(P)

        # print at sample points
        if theta in (0,90,180,270,360,450,540,630,720) or (s % 10 == 0):
            print(f"theta={theta:.1f} deg, V={cylinder.volume*1e6:.6f} cc, P={P:.6g} Pa, mass={mass:.12g} kg, piston_vel={velocity:.6g} m/s, set_vel_ok={set_vel_ok}")

    Vmin = min(volumes); Vmax = max(volumes)
    idx_min = volumes.index(Vmin); idx_max = volumes.index(Vmax)

    print('\nVolume results:')
    print(f' Vmin (cc) = {Vmin*1e6:.6f} at theta={idx_min} deg')
    print(f' Vmax (cc) = {Vmax*1e6:.6f} at theta={idx_max} deg')
    print(f' Effective CR = {Vmax/Vmin:.6f}')

    initial_mass = masses[0]; final_mass = masses[-1]
    max_dev = max(abs(m - initial_mass) for m in masses)

    print('\nMass: initial={:.12g} kg, final={:.12g} kg, max_dev_from_initial={:.12g} kg'.format(initial_mass, final_mass, max_dev))

    # gamma and theoretical
    try:
        cp = gas.cp_mass; cv = gas.cv_mass; gamma = cp/cv
    except Exception:
        gamma = None
    P1 = AMBIENT_P
    V1 = V_BDC
    V2 = V_TDC
    if gamma is not None:
        P2_theory = P1 * (V1/V2)**gamma
    else:
        P2_theory = None

    P_at_TDC = pressures[volumes.index(min(volumes))]

    print('\nCompression results:')
    print(f' P_at_TDC = {P_at_TDC:.6g} Pa')
    if P2_theory is not None:
        print(f' P2_theory = {P2_theory:.6g} Pa')
        print(f' ratio simulated/theory = {P_at_TDC / P2_theory:.6g}')

    return {
        'Vmin_cc': Vmin*1e6, 'Vmax_cc': Vmax*1e6, 'CR': Vmax/Vmin,
        'initial_mass': initial_mass, 'final_mass': final_mass, 'max_dev': max_dev,
        'P_at_TDC': P_at_TDC, 'P2_theory': P2_theory
    }

if __name__ == '__main__':
    res = run_closed_wall_test()
    print('\nTest completed (diagnostic-only).')