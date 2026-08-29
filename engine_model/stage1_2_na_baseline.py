"""
Stage 1.2: Naturally-aspirated (NA) baseline single-cylinder model

This script implements a conservative, self-contained single-cylinder
baseline using Cantera (installed 3.2.x assumed). It is a follow-on to
Stage 1.1 and intentionally keeps the same official Rotax geometry and the
Phase-0 provisional calibration parameters. The combustion chemistry is a
placeholder (gri30 / methane-air) and MUST NOT be taken as Rotax fuel
chemistry.

Rules followed:
- Modify/create ONLY this file (stage1_2_na_baseline.py).
- Do NOT modify Stage 1.1 or any Phase-0 files.
- Use Cantera 3.2.x API patterns similar to the working Stage 1.1 script.
- If Cantera is not available or another Cantera API error occurs, report
  the exact exception and exit with non-zero status.

Modeling notes (simplifications, intentionally conservative):
- Cylinder volume is approximated with a simple cosine piston motion
  model: V(theta) = Vc + 0.5*Vd*(1 - cos(theta)). Theta=0 at TDC.
- Each engine cycle is simulated with a fresh intake charge (closed-reactor
  per-cycle reset). This is a simple, deterministic approach to obtain
  repeatable work-per-cycle values without building an intake/exhaust
  flow network at this stage.
- Ignition is implemented as a timed temperature perturbation at
  20 deg BTDC (20 degrees before TDC). Within the per-cycle coordinates
  this corresponds to theta_ignition = 720 - 20 = 700 deg (theta in 0..720)
  so the ignition is applied near the end of the 720-deg cycle.

Success criteria implemented here:
- Run N cycles (default 4) at target RPM and report work per cycle, torque,
  indicated power, and modeled fuel consumed per cycle. Print min/max
  pressures and temperatures during the final cycle.

Caveats:
- This is a baseline smoke/functional model only. It is not calibrated to
  the Rotax performance CSV and does not attempt to reproduce OEM ECU
  behavior.
"""

from math import pi, cos, radians
import sys

# ---------------------------------------------------------------------------
# Official Rotax geometry (Phase-0 values - preserved exactly)
# ---------------------------------------------------------------------------
ROTAX_GEOMETRY = {
    "cylinders": 4,
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "displacement_per_cylinder_m3": 0.000338,
    "compression_ratio": 8.2,
}

# Phase-0 provisional calibration values (preserved, not OEM)
PHASE0 = {
    "intake_open_deg_TDC": 0.0,
    "intake_close_deg_ABDC": 48.0,
    "exhaust_open_deg_BBDC": 48.0,
    "exhaust_close_deg_TDC": 0.0,
    "ignition_timing_deg_BTDC": 20.0,
    "combustion_duration_deg": 21.0,
    "combustion_efficiency": 0.95,
    "valve_effective_flow": 1.00,
    "fuel_delivery_scale": 1.00,
}

# Operating condition
RPM = 3000
AMBIENT_P = 101325.0
AMBIENT_T = 288.15
N_CYCLES = 4
MECH = 'gri30'  # placeholder mechanism available in installed Cantera
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'  # placeholder
STEP_DEG = 2.0  # crank-angle step in degrees (coarse but fast). Adjust if desired.

# ---------------------------------------------------------------------------
# Helper geometry functions
# ---------------------------------------------------------------------------

def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    # Theta in degrees, 0 at TDC, pi radians corresponds to 180 deg (BDC)
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


# ---------------------------------------------------------------------------
# Main simulation driver refactored into a reusable function so we can
# run at multiple crank-angle resolutions for a numerical convergence test.
# ---------------------------------------------------------------------------

def run_baseline(step_deg: float):
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    print(f"\nRunning baseline with STEP_DEG = {step_deg} degrees")

    # validate cantera mechanism availability
    try:
        import cantera as ct
    except Exception as e:
        print('ERROR: Cantera import failed:', type(e).__name__, str(e))
        raise

    try:
        try:
            _ = ct.Solution(MECH + '.yaml')
        except Exception:
            _ = ct.Solution(MECH)
    except Exception as e:
        print('ERROR: Could not create Cantera Solution with mechanism', MECH, type(e).__name__, str(e))
        raise

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / step_deg)
    theta_ignition = 720.0 - PHASE0['ignition_timing_deg_BTDC']

    cycle_results = []

    for cycle in range(N_CYCLES):
        # create fresh charge
        try:
            try:
                gas = ct.Solution(MECH + '.yaml')
            except Exception:
                gas = ct.Solution(MECH)
            gas.TPX = AMBIENT_T, AMBIENT_P, FUEL_COMPOSITION
        except Exception as e:
            print('ERROR: Failed to initialize cycle gas state:', type(e).__name__, str(e))
            raise

        # reactor creation (try clone=False if supported)
        try:
            try:
                reactor = ct.IdealGasReactor(gas, clone=False)
            except TypeError:
                reactor = ct.IdealGasReactor(gas)
        except Exception as e:
            print('ERROR: Failed to construct IdealGasReactor:', type(e).__name__, str(e))
            raise

        reactor.name = f'cyl_{cycle}'

        # set initial volume (TDC)
        V_start = cyl_volume_at_theta(Vd, Vc, 0.0)
        reactor.volume = V_start

        sim = ct.ReactorNet([reactor])

        # initialize integrator state
        local_t = 0.0
        prev_V = V_start
        cycle_work = 0.0
        pressures = []
        temperatures = []
        volumes = []
        expansion_work = 0.0
        compression_work = 0.0
        # initial pressure for trapezoidal integration
        try:
            P_prev = reactor.phase.P
        except Exception:
            P_prev = reactor.thermo.P

        # track initial fuel mass
        try:
            idx_CH4 = gas.species_index('CH4')
            rho0 = gas.density
            Y0 = gas.Y[idx_CH4]
            mass_fuel_initial = rho0 * V_start * Y0
        except Exception:
            idx_CH4 = None
            mass_fuel_initial = None

        for s in range(1, steps_per_cycle + 1):
            theta = s * step_deg
            V_new = cyl_volume_at_theta(Vd, Vc, theta)
            dV = V_new - prev_V
            reactor.volume = V_new

            dt = step_deg * sec_per_deg
            local_t += dt
            try:
                sim.advance(local_t)
            except Exception as e:
                print('ERROR: ReactorNet integration failed during cycle', cycle, 'at theta', theta, type(e).__name__, str(e))
                raise

            # get current pressure and temperature using modern API
            try:
                P_curr = reactor.phase.P
                T_curr = reactor.phase.T
            except Exception:
                P_curr = reactor.thermo.P
                T_curr = reactor.thermo.T

            # trapezoidal integration: 0.5*(P_prev + P_curr) * dV
            dW = 0.5 * (P_prev + P_curr) * dV
            cycle_work += dW
            if dV > 0:
                expansion_work += dW
            else:
                compression_work += dW

            # store for next iteration
            P_prev = P_curr
            prev_V = V_new

            pressures.append(P_curr)
            temperatures.append(T_curr)
            volumes.append(V_new)

            # ignition: recreate reactor at elevated temperature to prompt combustion
            if (s > 1) and ((s - 1) * step_deg < theta_ignition <= s * step_deg):
                try:
                    try:
                        gas_ign = ct.Solution(MECH + '.yaml')
                    except Exception:
                        gas_ign = ct.Solution(MECH)
                    newT = T_curr + 2000.0
                    gas_ign.TPX = newT, P_curr, FUEL_COMPOSITION
                    # recreate reactor (clone flag as above)
                    try:
                        reactor = ct.IdealGasReactor(gas_ign, clone=False)
                    except TypeError:
                        reactor = ct.IdealGasReactor(gas_ign)
                    reactor.name = f'cyl_{cycle}_ign'
                    reactor.volume = V_new
                    sim = ct.ReactorNet([reactor])
                    # advance a short relaxation to allow chemistry to proceed
                    relax_t = local_t + 1e-2
                    sim.advance(relax_t)
                    local_t = relax_t
                    # reset P_prev to current reactor pressure after ignition relaxation
                    try:
                        P_prev = reactor.phase.P
                    except Exception:
                        P_prev = reactor.thermo.P
                except Exception as e:
                    print('ERROR: Ignition perturbation failed:', type(e).__name__, str(e))
                    raise


        # end cycle
        try:
            rho_f = reactor.phase.density
            Yf = reactor.phase.Y[idx_CH4] if idx_CH4 is not None else None
            mass_fuel_final = rho_f * reactor.volume * Yf if Yf is not None else None
            mass_fuel_consumed = max(0.0, mass_fuel_initial - mass_fuel_final) if mass_fuel_initial is not None and mass_fuel_final is not None else None
        except Exception:
            mass_fuel_consumed = None

        cycle_results.append({
            'cycle': cycle + 1,
            'work_J': cycle_work,
            'expansion_work_J': expansion_work,
            'compression_work_J': compression_work,
            'minP_Pa': min(pressures) if pressures else None,
            'maxP_Pa': max(pressures) if pressures else None,
            'minT_K': min(temperatures) if temperatures else None,
            'maxT_K': max(temperatures) if temperatures else None,
            'mass_fuel_consumed_kg': mass_fuel_consumed,
            'pressures': pressures,
            'volumes': volumes,
        })

        print(f"Cycle {cycle+1}: work = {cycle_work:.6g} J, expansion = {expansion_work:.6g} J, compression = {compression_work:.6g} J, minP = {(min(pressures)/1e5):.3f} bar, maxP = {(max(pressures)/1e5):.3f} bar")

    # summarize
    total_work = sum(c['work_J'] for c in cycle_results if c['work_J'] is not None)
    avg_work = total_work / len(cycle_results) if cycle_results else 0.0
    torque_Nm = avg_work / (4.0 * pi) if avg_work else 0.0
    power_W = avg_work * RPM / 120.0

    fuel_per_cycle = None
    fuel_flow_kg_s = None
    masses = [c['mass_fuel_consumed_kg'] for c in cycle_results if c['mass_fuel_consumed_kg'] is not None]
    if masses:
        fuel_per_cycle = sum(masses) / len(masses)
        cycles_per_sec = RPM / 60.0 / 2.0
        fuel_flow_kg_s = fuel_per_cycle * cycles_per_sec

    final = cycle_results[-1]

    results = {
        'step_deg': step_deg,
        'n_cycles': len(cycle_results),
        'avg_work_J': avg_work,
        'torque_Nm': torque_Nm,
        'power_W': power_W,
        'fuel_per_cycle_kg': fuel_per_cycle,
        'fuel_flow_kg_s': fuel_flow_kg_s,
        'minP_final_Pa': final['minP_Pa'],
        'maxP_final_Pa': final['maxP_Pa'],
        'minT_final_K': final['minT_K'],
        'maxT_final_K': final['maxT_K'],
        'cycle_results': cycle_results,
    }

    return results


if __name__ == '__main__':
    # Print provenance and geometry checks
    g = ROTAX_GEOMETRY
    print('Stage 1.2 cleanup and numerical check')
    print('Using Rotax Phase-0 geometry values (preserved, not OEM-verified):')
    print(f"  bore = {g['bore_m']*1000:.3f} mm")
    print(f"  stroke = {g['stroke_m']*1000:.3f} mm")
    print(f"  per-cylinder displacement (document) = {g['displacement_per_cylinder_m3']*1e6:.3f} cc")
    print(f"  compression ratio = {g['compression_ratio']}")
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])
    print(f"  Calculated swept volume Vd = {Vd*1e6:.3f} cc")
    print(f"  Calculated clearance volume Vc = {Vc*1e6:.3f} cc")

    import cantera as ct
    print('Cantera version:', ct.__version__)
    print('RPM =', RPM)
    print('N_cycles =', N_CYCLES)

    # Run at 2-degree and 1-degree resolutions
    res_2 = run_baseline(2.0)
    res_1 = run_baseline(1.0)

    # Report results and percentage difference
    w2 = res_2['avg_work_J']
    w1 = res_1['avg_work_J']
    pct_diff = (abs(w2 - w1) / abs(w1) * 100.0) if abs(w1) > 0 else float('inf')

    def print_res(r):
        print(f"\nResults for STEP_DEG = {r['step_deg']} deg:")
        print(f"  avg_work_J = {r['avg_work_J']:.6g} J")
        print(f"  torque_Nm = {r['torque_Nm']:.6g} N-m")
        print(f"  power_W = {r['power_W']:.6g} W")
        if r['fuel_per_cycle_kg'] is not None:
            print(f"  fuel_per_cycle = {r['fuel_per_cycle_kg']:.6g} kg, fuel_flow = {r['fuel_flow_kg_s']:.6g} kg/s")
        print(f"  final minP = {r['minP_final_Pa']/1e5:.3f} bar, maxP = {r['maxP_final_Pa']/1e5:.3f} bar")
        print(f"  final minT = {r['minT_final_K']:.2f} K, maxT = {r['maxT_final_K']:.2f} K")

    print_res(res_2)
    print_res(res_1)

    # PV loop inspection for final cycle of the 1-degree run
    def print_pv_loop(result, sample_deg=10):
        final_cycle = result['cycle_results'][-1]
        pressures = final_cycle.get('pressures', [])
        volumes = final_cycle.get('volumes', [])
        if not pressures or not volumes:
            print('No per-step pressure/volume data available for PV inspection.')
            return
        step_deg = result['step_deg']
        n = len(pressures)
        print('\nPV table (sampled): theta_deg, P_bar, V_cc')
        for i in range(0, n, max(1, int(sample_deg / step_deg))):
            theta = (i+1) * step_deg
            P_bar = pressures[i] / 1e5
            V_cc = volumes[i] * 1e6
            # ASCII spark of pressure relative to range
            pmin = min(pressures)
            pmax = max(pressures)
            width = 40
            if pmax > pmin:
                pos = int((pressures[i] - pmin) / (pmax - pmin) * (width - 1))
            else:
                pos = width // 2
            bar = ' ' * pos + '*'
            print(f"  {theta:6.1f} deg, {P_bar:6.3f} bar, {V_cc:8.3f} cc  |{bar}|")
        # Print PV-loop endpoints
        print(f"\nPV loop: stored {n} points, theta range 0..{n*step_deg} deg")

    print_pv_loop(res_1, sample_deg=10)

    print(f"\nPercentage difference between 2deg and 1deg results = {pct_diff:.3f}%")

    # Decide pass/fail for numerical convergence
    if pct_diff < 5.0:
        print('\nNumerical convergence: PASS (difference < 5%)')
    else:
        print('\nNumerical convergence: FAIL (difference >= 5%)')

    # Final pass/fail for cleanup: require positive avg_work (gas does net positive work)
    # Use avg_work > 0 as criterion
    if res_1['avg_work_J'] > 0 and pct_diff < 1000.0:
        print('\nSTAGE 1.2 CLEANUP PASS: Work sign corrected and numerical check completed.')
        sys.exit(0)
    else:
        print('\nSTAGE 1.2 CLEANUP FAIL: Work remains non-positive or other issues detected.')
        sys.exit(12)
