import importlib.util, random, shutil, sys, time
from pathlib import Path

shutil.copyfile(
    "engine_model/stage1_3_hybrid_engine_output.py.perfbak",
    "engine_model/_old_engine_ref.py",
)

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load " + path)
    m = importlib.util.module_from_spec(spec)
    # Dataclasses resolve annotations via sys.modules, so register first.
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m

old = load("engine_model/_old_engine_ref.py", "old_engine")
from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput as New

mo, mn = old.Stage13HybridEngineOutput(), New()
rng = random.Random(4242)
FIELDS = ("power_kW", "fuelflow_kgh", "p_plenum_bar", "t_plenum_K", "torque_Nm",
          "case_no", "exact", "interpolated", "extrapolated", "validation_status")

same = diff = err_both = err_split = 0
worst = 0.0
examples = []
for _ in range(1500):
    r = rng.uniform(3000, 5800); th = rng.uniform(56.5, 100.0); al = rng.uniform(0, 22999)
    try: a = mo.query(r, th, al)
    except Exception: a = None
    try: b = mn.query(r, th, al)
    except Exception: b = None
    if a is None and b is None: err_both += 1; continue
    if (a is None) != (b is None):
        err_split += 1
        if len(examples) < 3: examples.append(("raise mismatch", r, th, al))
        continue
    bad = False
    for f in FIELDS:
        x, y = getattr(a, f), getattr(b, f)
        if isinstance(x, float) and isinstance(y, float):
            worst = max(worst, abs(x - y))
            if abs(x - y) > 1e-9:
                bad = True
                if len(examples) < 3: examples.append((f, r, th, al))
        elif x != y:
            bad = True
            if len(examples) < 3: examples.append((f, r, th, al))
    diff += bad; same += (not bad)

print("EQUIVALENCE over 1500 random points")
print("  identical %d   differing %d   raised in both %d   disagreed on raising %d"
      % (same, diff, err_both, err_split))
print("  largest numeric difference %.3e" % worst)
for e in examples:
    print("  example mismatch: %s at rpm %.1f thr %.1f alt %.0f" % e)

s = mn.query(3000.0, 56.5, 0.0, 15.0)
print("\nREGRESSION anchor case 2151")
print("  got     %s  %.8f kW  %.8f Nm  %.2f kg/h  %.4f bar  %.2f K"
      % (s.case_no, s.power_kW, s.torque_Nm, s.fuelflow_kgh, s.p_plenum_bar, s.t_plenum_K))
print("  expect  2151  15.36454167 kW  48.90685510 Nm  6.02 kg/h  0.6256 bar  289.85 K")

from engine_model.stage5_simulation_pipeline import run_mission_realistic
from engine_model.stage7_fault_models import apply_fault
from generate_stage7_abnormal_dataset import build_config

print("\nTIMING with shared model")
tot_rows = tot_t = 0.0
for mt in ("NORMAL","HIGH_ALTITUDE","ENDURANCE","HOT_WEATHER","HIGH_POWER","RAPID_THROTTLE"):
    cfg = build_config(mt, "TIME_"+mt, 1234)
    t0 = time.perf_counter()
    rows = run_mission_realistic(cfg, engine_seed=1, engine_model=mn)
    dt = time.perf_counter() - t0
    tot_rows += len(rows); tot_t += dt
    print("  %-16s %6d rows  %6.2f s" % (mt, len(rows), dt))
t0 = time.perf_counter()
apply_fault(rows, engine_id="ENG_0251", fault_type="misfire", severity="severe", seed=1)
ft = time.perf_counter() - t0
per = tot_t / 6.0
s6 = per * 250 * 6; s7 = (per + ft) * 40 * 6 * 5 * 3
print("  rows/s %.0f   (was 56)" % (tot_rows / tot_t))
print("  stage 6 ~%.1f min   stage 7 ~%.1f h   total ~%.1f h" % (s6/60, s7/3600, (s6+s7)/3600))

Path("engine_model/_old_engine_ref.py").unlink(missing_ok=True)
