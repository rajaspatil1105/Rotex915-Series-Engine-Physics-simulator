import random
from engine_model.stage5_simulation_pipeline import run_mission_realistic
from engine_model.stage7_fault_models import apply_fault
from generate_stage7_abnormal_dataset import build_config

print("%-22s %-10s %6s %8s %8s %8s %8s" % ("fault", "severity", "scale", "dPower", "dFuel", "dCool", "dOilP"))
for fault in ("misfire", "cooling_degradation", "lubrication_degradation",
              "sensor_drift", "fuel_pressure_deviation"):
    for sev in ("mild", "severe"):
        seed = abs(hash((fault, sev))) % 99991
        cfg = build_config("NORMAL", "SMOKE_%s_%s" % (fault[:4], sev[:4]), seed)
        healthy = run_mission_realistic(cfg, engine_seed=3)
        scale = 0.75 + 0.50 * random.Random(seed * 31 + 17).random()
        bad = apply_fault(healthy, engine_id="ENG_0251", fault_type=fault,
                          severity=sev, seed=seed, magnitude_scale=scale)
        worst = None
        for h, f in zip(healthy, bad):
            d = f if isinstance(f, dict) else f.to_dict()
            if float(d.get("fault_envelope", 0.0)) > 0.95:
                dp = float(d["power_kW"]) - float(h.power_kW)
                if worst is None or abs(dp) > abs(worst[0]):
                    worst = (dp,
                             float(d["fuelflow_kgh"]) - float(h.fuelflow_kgh),
                             float(d["coolant_temp_C"]) - float(h.coolant_temp_C),
                             float(d["oil_pressure_bar"]) - float(h.oil_pressure_bar))
        if worst is None:
            print("%-22s %-10s %6.2f   no full-severity frames" % (fault, sev, scale))
        else:
            print("%-22s %-10s %6.2f %+8.2f %+8.3f %+8.2f %+8.3f"
                  % (fault, sev, scale, worst[0], worst[1], worst[2], worst[3]))
