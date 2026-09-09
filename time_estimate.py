import time
from engine_model.stage5_simulation_pipeline import run_mission_realistic
from engine_model.stage7_fault_models import apply_fault
from generate_stage7_abnormal_dataset import build_config

tot_rows = tot_t = 0.0
for mt in ("NORMAL", "HIGH_ALTITUDE", "ENDURANCE", "HOT_WEATHER", "HIGH_POWER", "RAPID_THROTTLE"):
    cfg = build_config(mt, "TIME_" + mt, 1234)
    t0 = time.perf_counter()
    rows = run_mission_realistic(cfg, engine_seed=1)
    dt = time.perf_counter() - t0
    tot_rows += len(rows); tot_t += dt
    print("%-16s %6d rows  %6.2f s" % (mt, len(rows), dt))

t0 = time.perf_counter()
apply_fault(rows, engine_id="ENG_0251", fault_type="misfire", severity="severe", seed=1)
fault_t = time.perf_counter() - t0

per_mission = tot_t / 6.0
print("\nrows/mission avg %.0f   rows/s %.0f   fault overhead %.2f s" % (tot_rows/6, tot_rows/tot_t, fault_t))
s6 = per_mission * 250 * 6
s7 = (per_mission + fault_t) * 40 * 6 * 5 * 3
print("stage 6 (1500 missions)   ~%5.1f min" % (s6/60))
print("stage 7 (3600 missions)   ~%5.1f min  (%.1f h)" % (s7/60, s7/3600))
print("total                     ~%5.1f h  (+ CSV write and master build)" % ((s6+s7)/3600))
