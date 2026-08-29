"""
Piston-driven closed-reactor compression test using a Cantera Wall (diagnostic-only).

- Single ideal-gas reactor representing the cylinder, connected to a reservoir by a Wall.
- The Wall's velocity is set so the reactor volume follows the same V(theta) schedule.
- Logs per-degree mass/pressure/temperature to verify mass conservation and pressure rise.

This file is diagnostic-only and does not modify other project files.
"""

from math import pi, cos, radians, sin
import sys

ROTAX_GEOMETRY = {
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "compression_ratio": 8.2,
}
RPM = 3000
AMBIENT_P = 101325.0
AMBIENT_T = 288.15
MECH = 'gri30'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'
STEP_DEG = 1.0


def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


def dVdtheta(vd: float, theta_deg: float) -> float:
    # derivative dV/dtheta (m^3 per degree)
    theta_rad = radians(theta_deg)
    # dV/dtheta = 0.5 * vd * sin(theta) * d(theta_rad)/d(theta_deg)
    return 0.5 * vd * sin(theta_rad) * (pi / 180.0)


def run_wall_compression(step_deg: float):
    try:
        import cantera as ct
    except Exception as e:
        print('ERROR: Cantera import failed:', type(e).__name__, str(e))
        raise

    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    # piston area = cylinder bore area
    piston_area = pi * (g['bore_m'] ** 2) / 4.0

    # create gas
    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
    except Exception as e:
        print('ERROR: creating mechanism', type(e).__name__, str(e))
        raise

    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    # create cylinder reactor and a downstream reservoir connected by a Wall
    try:
        try:
            cylinder = ct.IdealGasReactor(gas, clone=False)
        except TypeError:
            cylinder = ct.IdealGasReactor(gas)
    except Exception as e:
        print('ERROR: creating reactor:', type(e).__name__, str(e))
        raise

    # create a large-volume second reactor to act as a reservoir (so it can be included in ReactorNet)
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
        print('ERROR: creating remote reactor:', type(e).__name__, str(e))
        raise

    # give the remote a large volume so it approximates a reservoir
    remote.volume = 1.0  # 1 m^3

    # initial volume at BDC so piston compresses toward Vmin
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    cylinder.volume = V_BDC

    # create wall (piston) between cylinder and remote reactor
    try:
        piston = ct.Wall(cylinder, remote)
    except Exception as e:
        print('ERROR: creating Wall:', type(e).__name__, str(e))
        raise

    # set wall area to piston area
    try:
        piston.area = piston_area
    except Exception:
        # older/newer APIs may differ; ignore if unavailable
        pass

    # ReactorNet with both reactors
    sim = ct.ReactorNet([cylinder, remote])

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / step_deg)

    pressures = []
    volumes = []
    temperatures = []
    masses = []

    local_t = 0.0

    # print ids
    print('Cantera version:', ct.__version__)
    print(f'debug ids: gas id={id(gas)}, cylinder.phase id={id(cylinder.phase)}, remote.phase id={id(remote.phase)}')

    for s in range(1, steps_per_cycle + 1):
        theta = s * step_deg
        V_target = cyl_volume_at_theta(Vd, Vc, theta)

        # compute required piston velocity to move from current volume to V_target over dt
        # dV/dt = piston_area * velocity  => velocity = (dV/dt) / piston_area
        # compute dV/dtheta then dV/dt = dV/dtheta * deg_per_sec
        dV_dth = dVdtheta(Vd, theta)
        dV_dt = dV_dth * deg_per_sec
        velocity = dV_dt / piston_area

        # set piston velocity on wall if supported
        set_velocity_ok = False
        try:
            # try property assignment
            piston.velocity = velocity
            set_velocity_ok = True
        except Exception:
            try:
                # try set method if available
                piston.set_velocity(velocity)
                set_velocity_ok = True
            except Exception:
                set_velocity_ok = False

        # advance sim by dt
        dt = step_deg * sec_per_deg
        local_t += dt
        try:
            sim.advance(local_t)
        except Exception as e:
            print('ERROR: ReactorNet advance failed at theta', theta, type(e).__name__, str(e))
            raise

        # read state
        try:
            P = cylinder.phase.P
            T = cylinder.phase.T
            rho = cylinder.phase.density
            mass = rho * cylinder.volume
        except Exception:
            P = cylinder.thermo.P
            T = cylinder.thermo.T
            rho = cylinder.thermo.density
            mass = rho * cylinder.volume

        # store
        pressures.append(P)
        volumes.append(cylinder.volume)
        temperatures.append(T)
        masses.append(mass)

        # print focused diagnostics in compression region and sampled elsewhere
        if (s % 10 == 0) or (120.0 <= theta <= 240.0):
            print(f"theta={theta:.1f} deg, V={cylinder.volume*1e6:.6f} cc, P={P:.6g} Pa, rho={rho:.6g} kg/m3, mass={mass:.12g} kg, piston_vel={velocity:.6g} m/s, set_vel_ok={set_velocity_ok}")

    # post-process
    Vmin = min(volumes)
    idx_min = volumes.index(Vmin)
    P_at_min = pressures[idx_min]

    # gamma
    try:
        cp = gas.cp_mass
        cv = gas.cv_mass
        gamma = cp / cv
    except Exception:
        gamma = None

    # compute theoretical P2 using V_BDC->Vmin
    P1 = AMBIENT_P
    V1 = V_BDC
    V2 = Vmin
    if gamma is not None and V2 > 0:
        P2_theory = P1 * (V1 / V2) ** gamma
    else:
        P2_theory = None

    results = {
        'Vd_cc': Vd*1e6,
        'Vc_cc': Vc*1e6,
        'Vmax_cc': max(volumes)*1e6,
        'Vmin_cc': Vmin*1e6,
        'mass_initial_kg': masses[0] if masses else None,
        'mass_final_kg': masses[-1] if masses else None,
        'P_at_min_Pa': P_at_min,
        'P2_theory_Pa': P2_theory,
        'pressures': pressures,
        'volumes': volumes,
        'temperatures': temperatures,
        'masses': masses,
    }
    return results


if __name__ == '__main__':
    res = run_wall_compression(STEP_DEG)
    print('\nResults:')
    print(f" Vd = {res['Vd_cc']:.6f} cc, Vc = {res['Vc_cc']:.6f} cc, Vmax = {res['Vmax_cc']:.6f} cc, Vmin = {res['Vmin_cc']:.6f} cc")
    print(f" initial_mass = {res['mass_initial_kg']:.12g} kg, final_mass = {res['mass_final_kg']:.12g} kg")
    print(f" P_at_min = {res['P_at_min_Pa']:.6g} Pa ({res['P_at_min_Pa']/1e5:.6g} bar)")
    if res['P2_theory_Pa'] is not None:
        print(f" P2_theory = {res['P2_theory_Pa']:.6g} Pa ({res['P2_theory_Pa']/1e5:.6g} bar)")

    # mass conservation summary
    m0 = res['mass_initial_kg']
    m1 = res['mass_final_kg']
    if m0 is not None and m1 is not None:
        delta = m1 - m0
        pct = (delta / m0 * 100.0) if m0 != 0 else None
        print(f"\nMass: initial={m0:.12g}, final={m1:.12g}, delta={delta:.12g} kg, pct={pct:.6g}%")

    ratio = None
    if res['P2_theory_Pa'] is not None and res['P2_theory_Pa'] > 0:
        ratio = res['P_at_min_Pa'] / res['P2_theory_Pa']
        print(f"\nSimulated/theoretical = {ratio:.6g}, percentage difference = {(ratio-1.0)*100.0:.3f}%")

    if ratio is not None and ratio > 0.5:
        print('\nCONCLUSION: Piston-driven compression behaves approximately as expected (pressure rises).')
        sys.exit(0)
    else:
        print('\nCONCLUSION: Piston-driven compression does NOT reach theoretical pressure.')
        sys.exit(12)