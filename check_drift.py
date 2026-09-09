import random
from engine_model.stage5_simulation_pipeline import run_mission_realistic
from engine_model.stage7_fault_models import apply_fault
from generate_stage7_abnormal_dataset import build_config

CHANNELS = ("coolant_temp_C", "oil_temperature_C", "oil_pressure_bar",
            "fuelflow_kgh", "p_plenum_bar", "EGT1_C")

cfg = build_config("NORMAL", "DRIFT_CHECK", 5150)
healthy = run_mission_realistic(cfg, engine_seed=4)
print("%-20s %10s %10s %10s" % ("drift channel", "healthy", "measured", "delta"))
for ch in CHANNELS:
    bad = apply_fault(healthy, engine_id="ENG_0251", fault_type="sensor_drift",
                      severity="severe", seed=5150, sensor_channel=ch)
    hit = None
    for h, f in zip(healthy, bad):
        d = f if isinstance(f, dict) else f.to_dict()
        if float(d.get("fault_envelope", 0.0)) > 0.95:
            hit = (float(getattr(h, ch)), float(d[ch]))
            break
    if hit is None:
        print("%-20s   no full-severity frame" % ch)
    else:
        flag = "" if abs(hit[1] - hit[0]) > 1e-9 else "   <-- NOT MOVING"
        print("%-20s %10.3f %10.3f %+10.3f%s" % (ch, hit[0], hit[1], hit[1] - hit[0], flag))
