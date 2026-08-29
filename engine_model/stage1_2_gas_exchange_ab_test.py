"""
Stage 1.2 diagnostic A/B test: original Python-macro valve diagnostic with diagnostic-only
outlet pressure = 99500 Pa and valve_coeff = 1e-3 for both inlet and outlet.

This file is a diagnostic copy. It does NOT modify the original Stage 1.2 baseline or
any Phase-0 CSV files.
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
STEP_DEG = 1.0  # aim for 1-degree resolution for diagnostic

# valve coefficients - set to 1e-3 for this A/B test
INLET_VALVE_COEFF = 1.e-3
OUTLET_VALVE_COEFF = 1.e-3

# ---------------------------------------------------------------------------
# Helper geometry functions
# ---------------------------------------------------------------------------

def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    return vd / (cr - 1.0)


def cyl_volume_at_theta(vd: float, vc: float, theta_deg: float) -> float:
    # Theta in degrees, 0 at TDC
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))


# ---------------------------------------------------------------------------
# Main diagnostic driver
# ---------------------------------------------------------------------------

def run_gas_exchange(step_deg: float):
    g = ROTAX_GEOMETRY
    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    print(f"\nRunning gas-exchange diagnostic A/B test with STEP_DEG = {step_deg} degrees")

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

    # convert valve timings into radians consistent with Cantera example crank_angle
    # Use crank_angle range 0..4*pi mapping to 0..720 deg
    def deg_to_rad(d):
        return d / 180.0 * pi

    # For ABDC/BTDC semantics, map into absolute crank-angle degrees (0..720) where
    # 0 deg = TDC of the firing stroke. BDC at 180 deg.
    intake_open_deg = PHASE0['intake_open_deg_TDC']
    intake_close_deg = 180.0 + PHASE0['intake_close_deg_ABDC']
    exhaust_open_deg = 180.0 - PHASE0['exhaust_open_deg_BBDC']
    exhaust_close_deg = PHASE0['exhaust_close_deg_TDC']

    # convert to radians for valve time_function (0..4*pi)
    inlet_open_rad = deg_to_rad(intake_open_deg)
    inlet_close_rad = deg_to_rad(intake_close_deg)
    outlet_open_rad = deg_to_rad(exhaust_open_deg)
    outlet_close_rad = deg_to_rad(exhaust_close_deg)

    # frequency for crank_angle(t)
    f = RPM / 60.0

    def crank_angle(t):
        # return crank-angle in radians in [0, 4*pi) corresponding to [0,720deg)
        return float((2.0 * pi * f * t) % (4.0 * pi))

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

        # define inlet reservoir (ambient)
        try:
            gas_inlet = ct.Solution(MECH + '.yaml')
        except Exception:
            gas_inlet = ct.Solution(MECH)
        gas_inlet.TPX = AMBIENT_T, AMBIENT_P, 'O2:0.21, N2:0.79'  # air-like
        inlet = ct.Reservoir(gas_inlet)

        # inlet valve (inlet -> cylinder)
        inlet_valve = ct.Valve(inlet, reactor)
        inlet_delta = (inlet_close_rad - inlet_open_rad) % (4.0 * pi)
        inlet_valve.valve_coeff = INLET_VALVE_COEFF * PHASE0['valve_effective_flow']
        inlet_valve.time_function = (lambda t, open_r=inlet_open_rad, delta=inlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)

        # define outlet reservoir (ambient/exhaust) - diagnostic-only lowered pressure
        try:
            gas_outlet = ct.Solution(MECH + '.yaml')
        except Exception:
            gas_outlet = ct.Solution(MECH)
        gas_outlet.TPX = AMBIENT_T, 99500.0, 'O2:0.21, N2:0.79'  # DIAGNOSTIC-ONLY: outlet lowered to 99.5 kPa
        outlet = ct.Reservoir(gas_outlet)

        # outlet valve (cylinder -> outlet)
        outlet_valve = ct.Valve(reactor, outlet)
        outlet_delta = (outlet_close_rad - outlet_open_rad) % (4.0 * pi)
        outlet_valve.valve_coeff = OUTLET_VALVE_COEFF * PHASE0['valve_effective_flow']
        outlet_valve.time_function = (lambda t, open_r=outlet_open_rad, delta=outlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)

        # Reactor network
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

        # accumulators for intake/exhaust mass flow
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

            # get current pressure and temperature
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

            # record instantaneous valve mass flows if available
            try:
                mdot_in_history.append(inlet_valve.mass_flow_rate)
            except Exception:
                mdot_in_history.append(0.0)
            try:
                mdot_out_history.append(outlet_valve.mass_flow_rate)
            except Exception:
                mdot_out_history.append(0.0)

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

                    # re-create valves attached to the new reactor so gas exchange continues
                    inlet = ct.Reservoir(gas_inlet)
                    inlet_valve = ct.Valve(inlet, reactor)
                    inlet_valve.valve_coeff = INLET_VALVE_COEFF * PHASE0['valve_effective_flow']
                    inlet_valve.time_function = (lambda t, open_r=inlet_open_rad, delta=inlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)

                    outlet = ct.Reservoir(gas_outlet)
                    outlet_valve = ct.Valve(reactor, outlet)
                    outlet_valve.valve_coeff = OUTLET_VALVE_COEFF * PHASE0['valve_effective_flow']
                    outlet_valve.time_function = (lambda t, open_r=outlet_open_rad, delta=outlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)

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

        # summarize intake/exhaust mass flows
        total_mdot_in = sum(mdot_in_history) * sec_per_deg * step_deg if mdot_in_history else 0.0
        total_mdot_out = sum(mdot_out_history) * sec_per_deg * step_deg if mdot_out_history else 0.0

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
            'total_mdot_in_kg': total_mdot_in,
            'total_mdot_out_kg': total_mdot_out,
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
    import cantera as ct
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    print('Stage 1.2 gas-exchange diagnostic A/B test (diagnostic-only)')
    print('Cantera version:', ct.__version__)
    print('RPM =', RPM)
    print('N_cycles =', N_CYCLES)

    res = run_gas_exchange(STEP_DEG)

    # produce plots for final cycle
    final_cycle = res['cycle_results'][-1]
    pressures = final_cycle.get('pressures', [])
    volumes = final_cycle.get('volumes', [])
    n = len(pressures)
    thetas = [(i+1) * res['step_deg'] for i in range(n)]

    # Pressure vs crank angle
    if pressures:
        plt.figure()
        plt.plot(thetas, [p/1e5 for p in pressures], label='p (bar)')
        plt.xlabel('crank angle (deg)')
        plt.ylabel('pressure (bar)')
        plt.title('Stage1.2 Gas-Exchange A/B: Pressure vs crank angle (final cycle)')
        plt.grid(True)
        plt.savefig(r'engine_model\stage1_2_gas_exchange_ab_pressure.png')
        print('Saved pressure plot to engine_model\\stage1_2_gas_exchange_ab_pressure.png')

    # PV loop
    if pressures and volumes:
        plt.figure()
        plt.plot([v*1e6 for v in volumes], [p/1e5 for p in pressures])
        plt.xlabel('volume (cc)')
        plt.ylabel('pressure (bar)')
        plt.title('Stage1.2 Gas-Exchange A/B: P-V loop (final cycle)')
        plt.grid(True)
        plt.savefig(r'engine_model\stage1_2_gas_exchange_ab_pv.png')
        print('Saved PV plot to engine_model\\stage1_2_gas_exchange_ab_pv.png')