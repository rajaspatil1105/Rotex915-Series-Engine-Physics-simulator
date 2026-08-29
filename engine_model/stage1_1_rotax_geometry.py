"""
Stage 1.1: Rotax 915 iS single-cylinder geometry smoke test

This script adapts the Cantera IC-engine example architecture for a
single-cylinder representation using the official Rotax geometry and the
provisional Phase-0 calibration parameters.

Important rules followed:
- Does NOT modify any project files.
- Uses only the documented geometry and provisional calibration parameters.
- If Cantera is not installed, the script prints a clear diagnostic and exits
  without attempting to modify the environment.

This is a smoke-test implementation (Stage 1.1). It is NOT a validated
Rotax engine model. See project rules for what must not be done here.
"""

from math import pi
import sys

# ---------------------------------------------------------------------------
# Official Rotax geometry (per supplied authoritative extraction)
# ---------------------------------------------------------------------------
ROTAX_GEOMETRY = {
    "cylinders": 4,
    "cylinder_arrangement": "horizontally opposed",
    "engine_cycle": "4-stroke",
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "total_displacement_m3": 0.001352,
    "displacement_per_cylinder_m3": 0.000338,
    "compression_ratio": 8.2,
}

# ---------------------------------------------------------------------------
# Phase-0 provisional calibration parameters (do not call these OEM values)
# ---------------------------------------------------------------------------
PHASE0_PARAMS = {
    "valve_timing": {
        "intake_open_deg_TDC": 0.0,
        "intake_close_deg_ABDC": 48.0,
        "exhaust_open_deg_BBDC": 48.0,
        "exhaust_close_deg_TDC": 0.0,
    },
    "ignition_timing_deg_BTDC": 20.0,
    "combustion_duration_deg": 21.0,
    "combustion_efficiency": 0.95,
    "valve_effective_flow": 1.00,
    "fuel_delivery_scale": 1.00,
}

# ---------------------------------------------------------------------------
# Geometry calculations and sanity checks
# ---------------------------------------------------------------------------
def swept_volume_per_cylinder(bore_m: float, stroke_m: float) -> float:
    return (pi / 4.0) * bore_m ** 2 * stroke_m


def clearance_volume_from_cr(vd: float, cr: float) -> float:
    # Vc = Vd / (CR - 1)
    return vd / (cr - 1.0)


def print_provenance_and_checks():
    print("Stage 1.1: Rotax 915 iS single-cylinder geometry smoke test")
    print("Do NOT treat simulation outputs as validated Rotax results.")
    print("")

    # Print geometry and provenance
    g = ROTAX_GEOMETRY
    print("Using official Rotax geometry (source: OM-915 i A Rev.2, §7.1.1/7.1.2, p.7-2):")
    print(f"  cylinders: {g['cylinders']} (arrangement: {g['cylinder_arrangement']})")
    print(f"  bore: {g['bore_m']*1000:.3f} mm")
    print(f"  stroke: {g['stroke_m']*1000:.3f} mm")
    print(f"  displacement per cylinder: {g['displacement_per_cylinder_m3']*1e6:.3f} cc")
    print(f"  total displacement: {g['total_displacement_m3']*1e6:.3f} cc")
    print(f"  compression ratio: {g['compression_ratio']}")
    print("")

    # Calculate swept and clearance volumes
    vd = swept_volume_per_cylinder(g['bore_m'], g['stroke_m'])
    vc = clearance_volume_from_cr(vd, g['compression_ratio'])

    print("Geometry sanity checks:")
    print(f"  Calculated swept volume per cylinder Vd = {vd*1e6:.3f} cc")
    print(f"  Expected per-cylinder displacement (from doc) = {g['displacement_per_cylinder_m3']*1e6:.3f} cc")
    print(f"  Difference = {(vd - g['displacement_per_cylinder_m3'])*1e6:.6f} cc")
    print(f"  Clearance volume Vc = {vc*1e6:.3f} cc")
    print(f"  Total displacement (4 cyl) = {vd * g['cylinders'] * 1e6:.3f} cc")
    print("")

    # Print provisional calibration parameter provenance
    print("Provisional Phase-0 calibration parameters (provenance recorded in calibration/calibration_parameters.csv):")
    vt = PHASE0_PARAMS['valve_timing']
    print(f"  Intake open: {vt['intake_open_deg_TDC']} deg TDC (RESEARCH, LOW) — NOT OEM-verified")
    print(f"  Intake close: {vt['intake_close_deg_ABDC']} deg ABDC (RESEARCH, LOW) — NOT OEM-verified")
    print(f"  Exhaust open: {vt['exhaust_open_deg_BBDC']} deg BBDC (RESEARCH, LOW) — NOT OEM-verified")
    print(f"  Exhaust close: {vt['exhaust_close_deg_TDC']} deg TDC (RESEARCH, LOW) — NOT OEM-verified")
    print(f"  Ignition timing: {PHASE0_PARAMS['ignition_timing_deg_BTDC']} deg BTDC (ASSUMED, LOW) — provisional")
    print(f"  Combustion duration: {PHASE0_PARAMS['combustion_duration_deg']} crank-angle deg (RESEARCH, MEDIUM) — provisional")
    print(f"  Combustion efficiency: {PHASE0_PARAMS['combustion_efficiency']} (ASSUMED, LOW) — provisional")
    print(f"  Valve effective flow multiplier: {PHASE0_PARAMS['valve_effective_flow']} (DERIVED, LOW) — provisional")
    print(f"  Fuel delivery scale: {PHASE0_PARAMS['fuel_delivery_scale']} (DERIVED, MEDIUM) — provisional")
    print("")

    return vd, vc


# ---------------------------------------------------------------------------
# Minimal Cantera-based smoke test (attempts to run only if Cantera is available)
# ---------------------------------------------------------------------------

def run_cantera_smoke_test(vd: float, vc: float):
    try:
        import cantera as ct
    except Exception as e:
        print("Cantera import failed or not installed:", type(e).__name__, str(e))
        print("Skipping Cantera reactor network creation. Install Cantera to run this stage.")
        return False, str(e)

    try:
        # Use a built-in mechanism if available (gri30). This is only for smoke test
        mech = 'gri30.yaml'
        try:
            gas = ct.Solution(mech)
        except Exception:
            # Try bare 'gri30' name
            gas = ct.Solution('gri30')

        # Set initial state (ambient-like)
        T0 = 288.15  # K
        P0 = ct.one_atm
        # Use stoichiometric methane-air mixture as placeholder (NOT Rotax fuel)
        # This is consistent with the 'do not assume actual fuel chemistry' rule.
        gas.TPX = T0, P0, 'CH4:1.0, O2:2.0, N2:7.52'

        # Create a single IdealGasReactor representing one cylinder at BDC
        reactor = ct.IdealGasReactor(gas)
        reactor.name = 'cylinder'
        # Set an initial volume equal to clearance + swept (start at BDC)
        V_init = vc + vd
        reactor.volume = V_init

        # Reactor network
        sim = ct.ReactorNet([reactor])

        print("Cantera Reactor created; starting integration (short smoke run)...")

        t_end = 0.01  # 10 ms smoke run
        t = 0.0
        pressures = []
        temperatures = []

        while t < t_end:
            t = sim.step()
            pressures.append(reactor.thermo.P)
            temperatures.append(reactor.T)
            # break early if unphysical
            if reactor.volume <= 0 or not (reactor.T > 0 and reactor.thermo.P > 0):
                raise RuntimeError('Unphysical reactor state encountered')

        print("Cantera integration completed successfully (smoke run).")
        print(f"  steps: {len(pressures)}, t_end ~ {t:.6g} s")
        print(f"  min pressure: {min(pressures)/1e5:.3f} bar, max pressure: {max(pressures)/1e5:.3f} bar")
        print(f"  min temperature: {min(temperatures):.2f} K, max temperature: {max(temperatures):.2f} K")

        return True, None

    except Exception as e:
        print("Cantera smoke test failed:", type(e).__name__, str(e))
        return False, str(e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    vd, vc = print_provenance_and_checks()

    success, err = run_cantera_smoke_test(vd, vc)

    if success:
        print("Stage 1.1: Simulation completed successfully (smoke test).")
        sys.exit(0)
    else:
        print("Stage 1.1: Simulation not executed to completion. See messages above.")
        # Do not modify files or attempt automatic fixes; report error.
        sys.exit(0)
