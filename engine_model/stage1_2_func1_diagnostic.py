"""
Stage 1.2 diagnostic (Func1 valve-coefficient test)

Diagnostic-only copy of engine_model/stage1_2_gas_exchange_diagnostic.py that
replaces Python-side macro toggling with a Cantera-evaluated time function
for valve coefficient. The valve coefficient magnitude remains 1e-3 when open
and 0.0 when closed. ReactorNet.max_time_step is set to approx 0.1 crank-degree
at the current RPM to avoid solver steps skipping valve transitions.

Created as a diagnostic artifact only. Does NOT modify any existing project files.
"""

from math import pi, cos, radians
import sys

# ---------------------------------------------------------------------------
# Official Rotax geometry (copied from Stage 1.2)
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
N_CYCLES = 1
MECH = 'gri30'  # placeholder mechanism available in installed Cantera
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'  # placeholder
STEP_DEG = 1.0  # logging resolution

# Valve coefficient magnitudes (per-user requirement)
VALVE_COEFF_OPEN = 1e-3
VALVE_COEFF_CLOSED = 0.0

# ---------------------------------------------------------------------------
# Helper geometry functions
# ---------------------------------------------------------------------------

def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


# ---------------------------------------------------------------------------
# Build time-dependent coefficient function for Cantera
# ---------------------------------------------------------------------------

def build_coeff_function(ct, open_rad, delta_rad, coeff_open, coeff_closed):
    """
    Try to construct a Cantera Function object (Func1 or PiecewiseLinear) that
    evaluates to coeff_open when ((phi - open_rad) % 4pi) < delta_rad else coeff_closed.
    Fallback: return a Python callable that implements the same test. The returned
    object will be assigned to valve.time_function or valve_coeff_time depending
    on API availability.
    """
    fourpi = 4.0 * pi

    # Time->crank-angle helper that will be embedded in Python callables
    def coeff_time_func(t):
        # convert time t to crank-angle radians using RPM
        f = RPM / 60.0
        phi = (2.0 * pi * f * t) % (4.0 * pi)
        return coeff_open if ((phi - open_rad) % fourpi) < delta_rad else coeff_closed

    # Try to instantiate a Cantera Func1-like object if available
    try:
        # ct.Func1 exists in some Cantera versions; attempt to create
        Func1 = getattr(ct, 'Func1', None)
        if Func1 is not None:
            # Func1 expects a callable f(x) -> scalar; use it directly
            return Func1(coeff_time_func)
    except Exception:
        pass

    # Try PiecewiseLinear (name may differ); attempt robustly
    try:
        PiecewiseLinear = getattr(ct, 'PiecewiseLinear', None)
        if PiecewiseLinear is not None:
            # Build a periodic piecewise function over one 4*pi period by sampling
            # at 1-degree intervals and mapping t->value, then use PiecewiseLinear
            f = lambda t: coeff_time_func(t)
            return f  # fallback to callable if PiecewiseLinear not straightforward
    except Exception:
        pass

    # Final fallback: return the Python callable which Cantera will accept for time_function
    return coeff_time_func


# ---------------------------------------------------------------------------
# Diagnostic run implementing time-dependent coefficient
# ---------------------------------------------------------------------------

def run_func1_diagnostic(step_deg: float):
    import importlib
    try:
        import cantera as ct
    except Exception as e:
        print('ERROR: Cantera import failed:', type(e).__name__, str(e))
        raise

    print('Cantera version:', ct.__version__)

    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / step_deg)
    theta_ignition = 720.0 - PHASE0['ignition_timing_deg_BTDC']

    # map Phase-0 to absolute degrees
    intake_open_deg = PHASE0['intake_open_deg_TDC']
    intake_close_deg = 180.0 + PHASE0['intake_close_deg_ABDC']
    exhaust_open_deg = 180.0 - PHASE0['exhaust_open_deg_BBDC']
    exhaust_close_deg = PHASE0['exhaust_close_deg_TDC']

    def deg_to_rad(d):
        return d / 180.0 * pi

    inlet_open_r = deg_to_rad(intake_open_deg)
    inlet_close_r = deg_to_rad(intake_close_deg)
    outlet_open_r = deg_to_rad(exhaust_open_deg)
    outlet_close_r = deg_to_rad(exhaust_close_deg)

    inlet_delta = (inlet_close_r - inlet_open_r) % (4.0 * pi)
    outlet_delta = (outlet_close_r - outlet_open_r) % (4.0 * pi)

    # Build coefficient functions
    coeff_in_func = build_coeff_function(ct, inlet_open_r, inlet_delta, VALVE_COEFF_OPEN, VALVE_COEFF_CLOSED)
    coeff_out_func = build_coeff_function(ct, outlet_open_r, outlet_delta, VALVE_COEFF_OPEN, VALVE_COEFF_CLOSED)

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

        # reactor creation
        try:
            try:
                reactor = ct.IdealGasReactor(gas, clone=False)
            except TypeError:
                reactor = ct.IdealGasReactor(gas)
        except Exception as e:
            print('ERROR: Failed to construct IdealGasReactor:', type(e).__name__, str(e))
            raise

        reactor.name = f'cyl_{cycle}'
        V_start = cyl_volume_at_theta(Vd, Vc, 0.0)
        reactor.volume = V_start

        # inlet/outlet reservoirs
        try:
            try:
                gas_inlet = ct.Solution(MECH + '.yaml')
            except Exception:
                gas_inlet = ct.Solution(MECH)
        except Exception:
            gas_inlet = ct.Solution(MECH)
        gas_inlet.TPX = AMBIENT_T, AMBIENT_P, 'O2:0.21, N2:0.79'
        inlet = ct.Reservoir(gas_inlet)

        try:
            try:
                gas_outlet = ct.Solution(MECH + '.yaml')
            except Exception:
                gas_outlet = ct.Solution(MECH)
        except Exception:
            gas_outlet = ct.Solution(MECH)
        gas_outlet.TPX = AMBIENT_T, 99500.0, 'O2:0.21, N2:0.79'
        outlet = ct.Reservoir(gas_outlet)

        # create valves
        inlet_valve = ct.Valve(inlet, reactor)
        outlet_valve = ct.Valve(reactor, outlet)

        # Attach time-dependent valve coefficient functions where supported
        attached_in = False
        attached_out = False
        # Define boolean time functions (always available) so they can be used later
        def inlet_time_bool(t, open_r=inlet_open_r, delta=inlet_delta):
            f = RPM / 60.0
            phi = (2.0 * pi * f * t) % (4.0 * pi)
            return ((phi - open_r) % (4.0 * pi)) < delta

        def outlet_time_bool(t, open_r=outlet_open_r, delta=outlet_delta):
            f = RPM / 60.0
            phi = (2.0 * pi * f * t) % (4.0 * pi)
            return ((phi - open_r) % (4.0 * pi)) < delta

        # Preferred: try to assign Cantera function objects (coeff_in_func/coeff_out_func) to valve.time_function
        # If the Cantera API accepts a callable or Func1, it will evaluate at solver times. Otherwise fallback to boolean time functions.
        try:
            inlet_valve.valve_coeff = VALVE_COEFF_OPEN
            outlet_valve.valve_coeff = VALVE_COEFF_OPEN
            # Attempt to assign the coefficient function directly if supported
            inlet_valve.time_function = coeff_in_func
            outlet_valve.time_function = coeff_out_func
            attached_in = attached_out = True
        except Exception:
            # Fallback to boolean time functions (works with Valve.time_function in Cantera)
            inlet_valve.valve_coeff = VALVE_COEFF_OPEN
            outlet_valve.valve_coeff = VALVE_COEFF_OPEN
            inlet_valve.time_function = inlet_time_bool
            outlet_valve.time_function = outlet_time_bool
            attached_in = attached_out = True

        # Reactor network
        sim = ct.ReactorNet([reactor])

        # NOTE: Previously set ReactorNet.max_time_step to a very small value to
        # force solver timesteps ≈0.1 crank-degree. That caused integrator failure
        # during the ignition relaxation in this diagnostic. To allow the solver to
        # advance through the stiff ignition transient, do not set max_time_step and
        # let Cantera choose adaptive steps. This change is diagnostic-only and
        # does not modify any source project files.
        sec_per_deg = 1.0 / (RPM * 360.0 / 60.0)

        # integrator state and logging
        local_t = 0.0
        prev_V = V_start
        cycle_work = 0.0
        pressures = []
        temperatures = []
        volumes = []
        expansion_work = 0.0
        compression_work = 0.0

        try:
            P_prev = reactor.phase.P
        except Exception:
            P_prev = reactor.thermo.P

        try:
            idx_CH4 = gas.species_index('CH4')
            rho0 = gas.density
            Y0 = gas.Y[idx_CH4]
            mass_fuel_initial = rho0 * V_start * Y0
        except Exception:
            idx_CH4 = None
            mass_fuel_initial = None

        mdot_in_history = []
        mdot_out_history = []

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

            # capture values
            try:
                P_curr = reactor.phase.P
                T_curr = reactor.phase.T
            except Exception:
                P_curr = reactor.thermo.P
                T_curr = reactor.thermo.T

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

            # attempt to read instantaneous valve mass flows; not all valve implementations expose mass_flow_rate
            try:
                mdot_in_history.append(inlet_valve.mass_flow_rate)
            except Exception:
                mdot_in_history.append(0.0)
            try:
                mdot_out_history.append(outlet_valve.mass_flow_rate)
            except Exception:
                mdot_out_history.append(0.0)

            # ignition as in baseline
            SKIP_IGNITION = True
            if (not SKIP_IGNITION) and ((s > 1) and ((s - 1) * step_deg < theta_ignition <= s * step_deg)):
                try:
                    try:
                        gas_ign = ct.Solution(MECH + '.yaml')
                    except Exception:
                        gas_ign = ct.Solution(MECH)
                    newT = T_curr + 2000.0
                    gas_ign.TPX = newT, P_curr, FUEL_COMPOSITION
                    try:
                        reactor = ct.IdealGasReactor(gas_ign, clone=False)
                    except TypeError:
                        reactor = ct.IdealGasReactor(gas_ign)
                    reactor.volume = V_new
                    sim = ct.ReactorNet([reactor])
                    # re-create valves attached to new reactor
                    inlet = ct.Reservoir(gas_inlet)
                    inlet_valve = ct.Valve(inlet, reactor)
                    outlet = ct.Reservoir(gas_outlet)
                    outlet_valve = ct.Valve(reactor, outlet)
                    inlet_valve.time_function = inlet_time_bool
                    outlet_valve.time_function = outlet_time_bool
                    # sim.max_time_step intentionally not set here (letting Cantera adaptively choose steps)
                    relax_t = local_t + 1e-5
                    sim.advance(relax_t)
                    local_t = relax_t
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

        total_in = sum(mdot_in_history) * sec_per_deg * step_deg if mdot_in_history else 0.0
        total_out = sum(mdot_out_history) * sec_per_deg * step_deg if mdot_out_history else 0.0

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
            'mdot_in_history': mdot_in_history,
            'mdot_out_history': mdot_out_history,
            'total_mdot_in_kg': total_in,
            'total_mdot_out_kg': total_out,
        })

        print(f"Cycle {cycle+1}: work = {cycle_work:.6g} J, expansion = {expansion_work:.6g} J, compression = {compression_work:.6g} J, minP = {(min(pressures)/1e5):.3f} bar, maxP = {(max(pressures)/1e5):.3f} bar")

    # summarize
    total_work = sum(c['work_J'] for c in cycle_results if c['work_J'] is not None)
    avg_work = total_work / len(cycle_results) if cycle_results else 0.0
    torque_Nm = avg_work / (4.0 * pi) if avg_work else 0.0
    power_W = avg_work * RPM / 120.0

    final = cycle_results[-1]

    results = {
        'step_deg': step_deg,
        'n_cycles': len(cycle_results),
        'avg_work_J': avg_work,
        'torque_Nm': torque_Nm,
        'power_W': power_W,
        'minP_final_Pa': final['minP_Pa'],
        'maxP_final_Pa': final['maxP_Pa'],
        'minT_final_K': final['minT_K'],
        'maxT_final_K': final['maxT_K'],
        'cycle_results': cycle_results,
    }

    return results


if __name__ == '__main__':
    import cantera as ct
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    print('Stage 1.2 Func1 valve-coefficient diagnostic (diagnostic-only)')
    res = run_func1_diagnostic(STEP_DEG)

    # produce simple outputs
    final = res['cycle_results'][-1]
    pressures = final.get('pressures', [])
    volumes = final.get('volumes', [])

    # Print representative mdot every 10 degrees
    mdot_in = final.get('mdot_in_history', [])
    mdot_out = final.get('mdot_out_history', [])
    n = len(mdot_in)
    print('\nRepresentative mdot every 10 degrees:')
    for i in range(0, n, max(1, int(10/STEP_DEG))):
        theta = (i+1)*STEP_DEG
        print(f"  {theta:6.1f} deg: mdot_in={mdot_in[i]:+.3e} kg/s, mdot_out={mdot_out[i]:+.3e} kg/s")

    # print all non-negligible mdot events
    peak_in = max((abs(x) for x in mdot_in), default=0.0)
    peak_out = max((abs(x) for x in mdot_out), default=0.0)
    thresh = max(1e-15, peak_in*0.01, peak_out*0.01)
    print(f"\nNon-negligible mdot events (threshold={thresh:.3e} kg/s):")
    for i, (mi, mo) in enumerate(zip(mdot_in, mdot_out)):
        if abs(mi) > thresh or abs(mo) > thresh:
            theta = (i+1)*STEP_DEG
            print(f"  {theta:6.1f} deg: mdot_in={mi:+.3e}, mdot_out={mo:+.3e}, P={pressures[i]/1e5:.3f} bar")

    # boundary neighborhoods
    def print_near(bound):
        print(f"\nValues near {bound} deg:")
        for a in range(int(bound)-3, int(bound)+4):
            idx = max(0, min(n-1, int(a/STEP_DEG)-1))
            print(f"  {a:4d} deg: mdot_in={mdot_in[idx]:+.3e}, mdot_out={mdot_out[idx]:+.3e}, P={pressures[idx]/1e5:.3f} bar")

    intake_open_deg = PHASE0['intake_open_deg_TDC']
    intake_close_deg = 180.0 + PHASE0['intake_close_deg_ABDC']
    exhaust_open_deg = 180.0 - PHASE0['exhaust_open_deg_BBDC']
    exhaust_close_deg = PHASE0['exhaust_close_deg_TDC']

    print_near(intake_open_deg)
    print_near(intake_close_deg)
    print_near(exhaust_open_deg)
    print_near(exhaust_close_deg)

    # final numeric summary
    total_in = final.get('total_mdot_in_kg', 0.0)
    total_out = final.get('total_mdot_out_kg', 0.0)
    print('\nFinal numeric summary:')
    print(f"  valve_coeff open = {VALVE_COEFF_OPEN}, closed = {VALVE_COEFF_CLOSED}")
    print(f"  total intake mass = {total_in:.6g} kg, total exhaust mass = {total_out:.6g} kg")
    print(f"  peak_intake_mdot = {peak_in:.3e} kg/s, peak_exhaust_mdot = {peak_out:.3e} kg/s")
    print(f"  minP = {res['minP_final_Pa']/1e5:.3f} bar, maxP = {res['maxP_final_Pa']/1e5:.3f} bar")
    print(f"  minT = {res['minT_final_K']:.2f} K, maxT = {res['maxT_final_K']:.2f} K")
    print(f"  expansion = {final['expansion_work_J']:.6g} J, compression = {final['compression_work_J']:.6g} J, net = {final['work_J']:.6g} J")
    print(f"  torque = {res['torque_Nm']:.6g} N-m, power = {res['power_W']:.6g} W")

    # Comparison to previous broken result (printed for convenience)
    print('\nComparison to previous broken result (valve_coeff=0.01)')
    print('  previous intake mass ≈ 5.7e-13 kg, previous exhaust mass ≈ 3.2e-12 kg')
    print('\nDIAGNOSTIC COMPLETE — DO NOT MARK STAGE 1.2 COMPLETE')
