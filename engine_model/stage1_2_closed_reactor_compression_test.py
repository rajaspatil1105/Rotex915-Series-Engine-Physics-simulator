"""
Closed-reactor compression test (diagnostic-only)

Creates a single IdealGasReactor, applies the same piston-volume schedule (theta 0..720 deg)
with STEP_DEG sampling, and advances a ReactorNet. No valves, no reservoirs, no ignition.

Purpose: verify that changing reactor.volume + sim.advance produces an adiabatic compression
and the cylinder pressure rises toward the theoretical isentropic value.

This diagnostic file is created (only) and does not modify any existing project files.
"""

from math import pi, cos, radians
import sys

# Reuse the same geometry and operating values as Stage 1.2 baseline
ROTAX_GEOMETRY = {
    "cylinders": 4,
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "displacement_per_cylinder_m3": 0.000338,
    "compression_ratio": 8.2,
}
RPM = 3000
AMBIENT_P = 101325.0
AMBIENT_T = 288.15
MECH = 'gri30'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'  # placeholder matching baseline
STEP_DEG = 1.0
N_CYCLES = 1

# helper geometry functions

def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


def run_closed_reactor(step_deg: float):
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    try:
        import cantera as ct
    except Exception as e:
        print('ERROR: Cantera import failed:', type(e).__name__, str(e))
        raise

    # mechanism availability
    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
    except Exception as e:
        print('ERROR: Could not create Cantera Solution with mechanism', MECH, type(e).__name__, str(e))
        raise

    # set initial state
    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION

    # create reactor
    try:
        try:
            reactor = ct.IdealGasReactor(gas, clone=False)
        except TypeError:
            reactor = ct.IdealGasReactor(gas)
    except Exception as e:
        print('ERROR: Failed to construct IdealGasReactor:', type(e).__name__, str(e))
        raise

    # initial volume set to BDC (theta=180) so the run compresses toward Vmin
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    reactor.volume = V_BDC

    sim = ct.ReactorNet([reactor])

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / step_deg)

    pressures = []
    volumes = []
    temperatures = []

    # track initial mass (use reactor.phase when available)
    try:
        rho0 = reactor.phase.density
    except Exception:
        rho0 = reactor.thermo.density
    mass_initial = rho0 * reactor.volume
    print(f"[debug] mass_initial computed = {mass_initial:.12g} kg, reactor.volume = {reactor.volume*1e6:.6f} cc, phase_density = {rho0:.6g} kg/m3")

    prev_V = V_BDC
    local_t = 0.0
    previous_mass = mass_initial

    # store P_prev for trapezoidal integration if desired
    try:
        P_prev = reactor.phase.P
    except Exception:
        P_prev = reactor.thermo.P

    # diagnostic ids to detect cloning/aliasing issues
    print(f"Diagnostic ids: gas id={id(gas)}, reactor.phase id={id(reactor.phase)}, reactor id={id(reactor)}")

    for s in range(1, steps_per_cycle + 1):
        theta = s * step_deg
        V_new = cyl_volume_at_theta(Vd, Vc, theta)
        dV = V_new - prev_V

        # preserve mass manually: read current mass, change volume, then restore density so mass stays constant
        try:
            rho_before = reactor.phase.density
        except Exception:
            rho_before = reactor.thermo.density
        mass_before = rho_before * reactor.volume

        # set the new geometric volume
        reactor.volume = V_new

        # try to restore mass by setting reactor.mass if available; fallback to setting density
        try:
            # some Cantera versions allow setting reactor.mass directly
            print(f"[debug] attempting reactor.mass assign: before assign reactor.mass={getattr(reactor, 'mass', 'NO_ATTR')}, mass_before={mass_before:.12g}")
            reactor.mass = mass_before
            print(f"[debug] after assign reactor.mass={getattr(reactor, 'mass', 'NO_ATTR')}")
        except Exception as ex:
            print(f"[debug] reactor.mass assign failed: {type(ex).__name__} {ex}")
            try:
                new_rho = mass_before / reactor.volume
                reactor.phase.set_density(new_rho)
                print(f"[debug] used reactor.phase.set_density new_rho={new_rho:.12g}")
            except Exception as e2:
                print(f"[debug] reactor.phase.set_density failed: {type(e2).__name__} {e2}")
                try:
                    reactor.thermo.set_density(new_rho)
                    print(f"[debug] used reactor.thermo.set_density new_rho={new_rho:.12g}")
                except Exception:
                    # if set_density not available, fall back and accept mass change
                    pass

        dt = step_deg * sec_per_deg
        local_t += dt
        try:
            sim.advance(local_t)
        except Exception as e:
            print('ERROR: ReactorNet integration failed at theta', theta, type(e).__name__, str(e))
            raise

        # read state
        try:
            P_curr = reactor.phase.P
            T_curr = reactor.phase.T
            rho = reactor.phase.density
        except Exception:
            P_curr = reactor.thermo.P
            T_curr = reactor.thermo.T
            rho = reactor.thermo.density

        mass = rho * reactor.volume
        pressures.append(P_curr)
        volumes.append(V_new)
        temperatures.append(T_curr)

        # instrumentation: print every 10 degrees and every 1 degree between 120..240
        if (s % 10 == 0) or (120.0 <= theta <= 240.0):
            dmass = mass - previous_mass
            print(f"theta={theta:.1f} deg, V={V_new*1e6:.6f} cc, P={P_curr:.6g} Pa, rho={rho:.6g} kg/m3, mass={mass:.12g} kg, dmass={dmass:.12g} kg")
        previous_mass = mass

        prev_V = V_new

    # final mass
    mass_final = rho * reactor.volume

    # find index of min volume (Vmin)
    Vmin = min(volumes)
    idx_min = volumes.index(Vmin)
    P_at_minV = pressures[idx_min]

    # compute gamma from cp/cv using mass-based properties
    try:
        cp = gas.cp_mass
        cv = gas.cv_mass
        gamma = cp / cv
    except Exception:
        # fallback using cp/Cv properties on thermo if available
        try:
            cp = reactor.thermo.cp_mass
            cv = reactor.thermo.cv_mass
            gamma = cp / cv
        except Exception:
            gamma = None

    # theoretical isentropic compression P2 = P1*(V1/V2)^gamma
    P1 = AMBIENT_P
    # Use BDC as the compression start volume
    V1 = V_BDC
    V2 = Vmin
    if gamma is not None and V2 > 0:
        P2_theory = P1 * (V1 / V2) ** gamma
    else:
        P2_theory = None

    results = {
        'Vd_m3': Vd,
        'Vc_m3': Vc,
        'Vmax_m3': max(volumes),
        'Vmin_m3': Vmin,
        'mass_initial_kg': mass_initial,
        'mass_final_kg': mass_final,
        'P_at_minV_Pa': P_at_minV,
        'gamma': gamma,
        'P2_theory_Pa': P2_theory,
        'pressures': pressures,
        'volumes': volumes,
        'temperatures': temperatures,
    }

    return results


def run_closed_reactor_recreate(step_deg: float):
    """Recreate the reactor each timestep to preserve mass explicitly.
    This is slower but ensures mass is conserved by setting density on the new reactor.
    """
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    import cantera as ct

    # initialize first reactor at BDC
    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
    except Exception as e:
        print('ERROR: Could not create Cantera Solution for recreate run', type(e).__name__, str(e))
        raise

    gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION
    V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
    try:
        reactor = ct.IdealGasReactor(gas, clone=False)
    except TypeError:
        reactor = ct.IdealGasReactor(gas)
    reactor.volume = V_BDC

    # initial mass
    try:
        rho0 = reactor.phase.density
    except Exception:
        rho0 = reactor.thermo.density
    mass = rho0 * reactor.volume

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / step_deg)

    pressures = []
    volumes = []
    temperatures = []

    local_t = 0.0

    for s in range(1, steps_per_cycle + 1):
        theta = s * step_deg
        V_new = cyl_volume_at_theta(Vd, Vc, theta)

        # mass is preserved from previous reactor
        mass_before = mass

        # create new gas and reactor with V_new, set density to preserve mass
        try:
            try:
                gas2 = ct.Solution(MECH + '.yaml')
            except Exception:
                gas2 = ct.Solution(MECH)
            # initialize with previous temperature if available
            T_prev = reactor.phase.T if hasattr(reactor, 'phase') else AMBIENT_T
            gas2.TP = T_prev, AMBIENT_P
            try:
                reactor2 = ct.IdealGasReactor(gas2, clone=False)
            except TypeError:
                reactor2 = ct.IdealGasReactor(gas2)
            reactor2.volume = V_new
            # set density to mass / V_new using thermo API
            new_rho = mass_before / reactor2.volume
            try:
                reactor2.thermo.set_density(new_rho)
            except Exception:
                # some APIs may not support set_density; fallback to leaving as-is
                pass
        except Exception as e:
            print('ERROR: Failed to recreate reactor at theta', theta, type(e).__name__, str(e))
            raise

        sim2 = ct.ReactorNet([reactor2])
        dt = step_deg * sec_per_deg
        local_t += dt
        try:
            sim2.advance(local_t)
        except Exception as e:
            print('ERROR: ReactorNet integration failed for recreated reactor at theta', theta, type(e).__name__, str(e))
            raise

        # read state
        try:
            P_curr = reactor2.phase.P
            T_curr = reactor2.phase.T
            rho = reactor2.phase.density
        except Exception:
            P_curr = reactor2.thermo.P
            T_curr = reactor2.thermo.T
            rho = reactor2.thermo.density

        # recompute mass (should equal mass_before)
        mass = rho * reactor2.volume

        pressures.append(P_curr)
        volumes.append(V_new)
        temperatures.append(T_curr)

        # swap reactor for next iteration
        reactor = reactor2

    # final results
    Vmin = min(volumes)
    idx_min = volumes.index(Vmin)
    P_at_minV = pressures[idx_min]

    try:
        cp = gas.cp_mass
        cv = gas.cv_mass
        gamma = cp / cv
    except Exception:
        gamma = None

    P1 = AMBIENT_P
    V1 = V_BDC
    V2 = Vmin
    P2_theory = P1 * (V1 / V2) ** gamma if gamma is not None else None

    results = {
        'Vd_m3': Vd,
        'Vc_m3': Vc,
        'Vmax_m3': max(volumes),
        'Vmin_m3': Vmin,
        'mass_initial_kg': mass_before,
        'mass_final_kg': mass,
        'P_at_minV_Pa': P_at_minV,
        'gamma': gamma,
        'P2_theory_Pa': P2_theory,
        'pressures': pressures,
        'volumes': volumes,
        'temperatures': temperatures,
    }
    return results


if __name__ == '__main__':
    print('Closed-reactor compression test (diagnostic-only)')
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])
    print(f"  bore = {g['bore_m']*1000:.3f} mm, stroke = {g['stroke_m']*1000:.3f} mm, CR = {g['compression_ratio']}")
    print(f"  Vd = {Vd*1e6:.6f} cc, Vc = {Vc*1e6:.6f} cc")

    import cantera as ct
    print('Cantera version:', ct.__version__)

    res = run_closed_reactor(STEP_DEG)

    print('\nResults:')
    print(f"  Vd = {res['Vd_m3']*1e6:.6f} cc, Vc = {res['Vc_m3']*1e6:.6f} cc, Vmax = {res['Vmax_m3']*1e6:.6f} cc, Vmin = {res['Vmin_m3']*1e6:.6f} cc")
    print(f"  initial_mass = {res['mass_initial_kg']:.12g} kg, final_mass = {res['mass_final_kg']:.12g} kg")
    print(f"  P_at_minV = {res['P_at_minV_Pa']:.6g} Pa ({res['P_at_minV_Pa']/1e5:.6g} bar)")
    if res['gamma'] is not None:
        print(f"  gamma = {res['gamma']:.6f}")
    if res['P2_theory_Pa'] is not None:
        print(f"  P2_theory = {res['P2_theory_Pa']:.6g} Pa ({res['P2_theory_Pa']/1e5:.6g} bar)")

    # report sampled PV around compression
    print('\nSample PV around compression (every 10 deg):')
    pressures = res['pressures']
    volumes = res['volumes']
    n = len(pressures)
    for i in range(0, n, 10):
        theta = (i+1) * STEP_DEG
        P_bar = pressures[i] / 1e5
        V_cc = volumes[i] * 1e6
        print(f"  {theta:6.1f} deg: P = {P_bar:.6f} bar, V = {V_cc:.6f} cc")

    # mass conservation
    mass_initial = res['mass_initial_kg']
    mass_final = res['mass_final_kg']
    abs_change = mass_final - mass_initial
    pct_change = (abs_change / mass_initial * 100.0) if mass_initial != 0 else None
    print(f"\nMass conservation: initial = {mass_initial:.12g}, final = {mass_final:.12g}, delta = {abs_change:.12g} kg, pct = {pct_change:.6g}%")

    # compare P_at_minV to theory
    if res['P2_theory_Pa'] is not None:
        ratio = res['P_at_minV_Pa'] / res['P2_theory_Pa']
        pct_diff = (ratio - 1.0) * 100.0
        print(f"\nSimulated/theoretical = {ratio:.6g}, percentage difference = {pct_diff:.3f}%")

    # quick decision
    if res['P_at_minV_Pa'] > 0 and res['P2_theory_Pa'] is not None:
        if res['P_at_minV_Pa'] / res['P2_theory_Pa'] > 0.5:
            print('\nCONCLUSION: Closed-reactor compression behaves approximately as expected (pressure rises).')
            sys.exit(0)
        else:
            print('\nCONCLUSION: Closed-reactor compression does NOT reach theoretical pressure; further investigation required.')
            sys.exit(11)
    else:
        print('\nCONCLUSION: Could not compute theoretical comparison; inspect outputs above.')
        sys.exit(13)
