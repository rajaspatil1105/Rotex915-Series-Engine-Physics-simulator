"""
Sweep outlet reservoir pressure diagnostic.
Runs a series of diagnostic gas-exchange tests with INLET/OUTLET valve_coeff=1e-3
and varying outlet reservoir pressure to identify when meaningful intake occurs.

Diagnostic-only: does not modify official project files.
"""
from math import pi, cos, radians

PRESSURES = [101325.0, 100800.0, 100500.0, 99500.0]
RPM = 3000
AMBIENT_T = 288.15
N_CYCLES = 1
MECH = 'gri30'
FUEL_COMPOSITION = 'CH4:1.0, O2:2.0, N2:7.52'
STEP_DEG = 1.0
INLET_VALVE_COEFF = 1e-3
OUTLET_VALVE_COEFF = 1e-3

from math import pi

def run_for_outlet_p(P_outlet):
    import cantera as ct
    from math import cos, radians
    # reuse Phase0 timings
    PHASE0 = {
        "intake_open_deg_TDC": 0.0,
        "intake_close_deg_ABDC": 48.0,
        "exhaust_open_deg_BBDC": 48.0,
        "exhaust_close_deg_TDC": 0.0,
        "ignition_timing_deg_BTDC": 20.0,
        "valve_effective_flow": 1.0,
    }
    # geometry
    g = {'bore_m':0.084, 'stroke_m':0.061, 'compression_ratio':8.2}
    def swept_volume_per_cylinder(bore_m, stroke_m):
        return (pi/4.0) * bore_m**2 * stroke_m
    def clearance_volume_from_cr(vd, cr):
        return vd/(cr-1.0)
    def cyl_volume_at_theta(vd, vc, theta_deg):
        from math import radians, cos
        theta_rad = radians(theta_deg)
        return vc + 0.5*vd*(1.0 - cos(theta_rad))

    Vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    Vc = clearance_volume_from_cr(Vd, g['compression_ratio'])

    deg_per_sec = RPM * 360.0 / 60.0
    sec_per_deg = 1.0 / deg_per_sec
    steps_per_cycle = int(720.0 / STEP_DEG)
    theta_ignition = 720.0 - PHASE0['ignition_timing_deg_BTDC']

    def deg_to_rad(d):
        return d/180.0 * pi
    intake_open_deg = PHASE0['intake_open_deg_TDC']
    intake_close_deg = 180.0 + PHASE0['intake_close_deg_ABDC']
    exhaust_open_deg = 180.0 - PHASE0['exhaust_open_deg_BBDC']
    exhaust_close_deg = PHASE0['exhaust_close_deg_TDC']
    inlet_open_rad = deg_to_rad(intake_open_deg)
    inlet_close_rad = deg_to_rad(intake_close_deg)
    outlet_open_rad = deg_to_rad(exhaust_open_deg)
    outlet_close_rad = deg_to_rad(exhaust_close_deg)
    inlet_delta = (inlet_close_rad - inlet_open_rad) % (4.0 * pi)
    outlet_delta = (outlet_close_rad - outlet_open_rad) % (4.0 * pi)
    f = RPM/60.0
    def crank_angle(t):
        return float((2.0 * pi * f * t) % (4.0 * pi))

    # one cycle
    try:
        try:
            gas = ct.Solution(MECH + '.yaml')
        except Exception:
            gas = ct.Solution(MECH)
        gas.TPX = AMBIENT_T, 101325.0, FUEL_COMPOSITION
    except Exception as e:
        raise
    try:
        try:
            reactor = ct.IdealGasReactor(gas, clone=False)
        except TypeError:
            reactor = ct.IdealGasReactor(gas)
    except Exception as e:
        raise
    V_start = cyl_volume_at_theta(Vd, Vc, 0.0)
    reactor.volume = V_start

    # inlet reservoir
    try:
        gas_inlet = ct.Solution(MECH + '.yaml')
    except Exception:
        gas_inlet = ct.Solution(MECH)
    gas_inlet.TPX = AMBIENT_T, 101325.0, 'O2:0.21, N2:0.79'
    inlet = ct.Reservoir(gas_inlet)

    inlet_valve = ct.Valve(inlet, reactor)
    inlet_valve.valve_coeff = INLET_VALVE_COEFF * PHASE0['valve_effective_flow']
    inlet_valve.time_function = (lambda t, open_r=inlet_open_rad, delta=inlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)

    # outlet reservoir with runtime P_outlet
    try:
        gas_outlet = ct.Solution(MECH + '.yaml')
    except Exception:
        gas_outlet = ct.Solution(MECH)
    gas_outlet.TPX = AMBIENT_T, P_outlet, 'O2:0.21, N2:0.79'
    outlet = ct.Reservoir(gas_outlet)

    outlet_valve = ct.Valve(reactor, outlet)
    outlet_valve.valve_coeff = OUTLET_VALVE_COEFF * PHASE0['valve_effective_flow']
    outlet_valve.time_function = (lambda t, open_r=outlet_open_rad, delta=outlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)

    sim = ct.ReactorNet([reactor])

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

    mdot_in_history = []
    mdot_out_history = []

    for s in range(1, steps_per_cycle + 1):
        theta = s * STEP_DEG
        V_new = cyl_volume_at_theta(Vd, Vc, theta)
        dV = V_new - prev_V
        reactor.volume = V_new
        dt = STEP_DEG * sec_per_deg
        local_t += dt
        sim.advance(local_t)
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
        try:
            mdot_in_history.append(inlet_valve.mass_flow_rate)
        except Exception:
            mdot_in_history.append(0.0)
        try:
            mdot_out_history.append(outlet_valve.mass_flow_rate)
        except Exception:
            mdot_out_history.append(0.0)
        # ignition recreate (same as diagnostic) - keep behavior consistent
        if (s > 1) and ((s - 1) * STEP_DEG < theta_ignition <= s * STEP_DEG):
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
                inlet = ct.Reservoir(gas_inlet)
                inlet_valve = ct.Valve(inlet, reactor)
                inlet_valve.valve_coeff = INLET_VALVE_COEFF * PHASE0['valve_effective_flow']
                inlet_valve.time_function = (lambda t, open_r=inlet_open_rad, delta=inlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)
                outlet = ct.Reservoir(gas_outlet)
                outlet_valve = ct.Valve(reactor, outlet)
                outlet_valve.valve_coeff = OUTLET_VALVE_COEFF * PHASE0['valve_effective_flow']
                outlet_valve.time_function = (lambda t, open_r=outlet_open_rad, delta=outlet_delta: ((crank_angle(t) - open_r) % (4.0 * pi)) < delta)
                sim = ct.ReactorNet([reactor])
                relax_t = local_t + 1e-2
                sim.advance(relax_t)
                local_t = relax_t
                try:
                    P_prev = reactor.phase.P
                except Exception:
                    P_prev = reactor.thermo.P
            except Exception:
                pass

    total_mdot_in = sum(mdot_in_history) * sec_per_deg * STEP_DEG if mdot_in_history else 0.0
    total_mdot_out = sum(mdot_out_history) * sec_per_deg * STEP_DEG if mdot_out_history else 0.0
    peak_in = max((abs(x) for x in mdot_in_history)) if mdot_in_history else 0.0
    peak_out = max((abs(x) for x in mdot_out_history)) if mdot_out_history else 0.0
    idx_in = next((i for i,x in enumerate(mdot_in_history) if abs(x)==peak_in), None)
    idx_out = next((i for i,x in enumerate(mdot_out_history) if abs(x)==peak_out), None)
    theta_in = (idx_in+1)*STEP_DEG if idx_in is not None else None
    theta_out = (idx_out+1)*STEP_DEG if idx_out is not None else None

    return {
        'P_outlet': P_outlet,
        'total_in': total_mdot_in,
        'total_out': total_mdot_out,
        'peak_in': peak_in,
        'theta_in': theta_in,
        'peak_out': peak_out,
        'theta_out': theta_out,
        'work_J': cycle_work,
        'minP': min(pressures)/1e5 if pressures else None,
        'maxP': max(pressures)/1e5 if pressures else None,
    }

if __name__ == '__main__':
    print('Outlet pressure sweep (diagnostic-only)')
    import json
    results = []
    for P in PRESSURES:
        print(f'Running outlet P = {P} Pa')
        r = run_for_outlet_p(P)
        print(json.dumps(r, indent=2))
        results.append(r)
    # print summary
    print('\nSummary:')
    for r in results:
        print(f"P={r['P_outlet']:.1f} Pa: total_in={r['total_in']:.6g} kg, total_out={r['total_out']:.6g} kg, peak_in={r['peak_in']:.6g} kg/s, peak_out={r['peak_out']:.6g} kg/s, net_work={r['work_J']:.6g} J, minP={r['minP']:.3f} bar, maxP={r['maxP']:.3f} bar")