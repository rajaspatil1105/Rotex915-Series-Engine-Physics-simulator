import statistics
from engine_model import stage4_realism as R
from engine_model.stage4_realism import Lag, SensorNoise, TAU_S, SENSOR_SIGMA

print("PART 1  pure lag, noise disabled")
print("  step 88 -> 110 C on the coolant channel, dt = 1 s")
lag = Lag(TAU_S["coolant_temp_C"])
lag.step(88.0, 1.0)
marks = {}
for t in range(1, 301):
    v = lag.step(110.0, 1.0)
    frac = (v - 88.0) / 22.0
    for target in (0.63, 0.86, 0.95):
        if target not in marks and frac >= target:
            marks[target] = t
print("    63%% at %3d s   (one tau  = %.0f s)" % (marks[0.63], TAU_S["coolant_temp_C"]))
print("    86%% at %3d s   (two tau  = %.0f s)" % (marks[0.86], 2 * TAU_S["coolant_temp_C"]))
print("    95%% at %3d s   (three tau= %.0f s)" % (marks[0.95], 3 * TAU_S["coolant_temp_C"]))
print("    max rate over the step: %.4f C/s" % (22.0 / TAU_S["coolant_temp_C"]))

print("\nPART 2  pure noise, one engine, constant true value")
n = SensorNoise(engine_seed=7)
truth = {"coolant_temp_C": 90.0, "oil_temperature_C": 100.0, "EGT_mean_C": 750.0,
         "oil_pressure_bar": 3.2, "fuelflow_kgh": 10.6, "rpm": 5000.0}
samples = {k: [] for k in truth}
for _ in range(4000):
    m = n.measure(truth)
    for k in truth:
        samples[k].append(m[k])
print("  %-18s %8s %8s %8s" % ("channel", "spec", "measured", "bias"))
for k in truth:
    print("  %-18s %8.3f %8.3f %+8.3f"
          % (k, SENSOR_SIGMA.get(k, 0.0), statistics.pstdev(samples[k]),
             statistics.mean(samples[k]) - truth[k]))

print("\nPART 3  bias is fixed per engine, not per sample")
for seed in (1, 2, 3):
    print("  engine %d coolant bias %+.3f C" % (seed, SensorNoise(seed).bias["coolant_temp_C"]))

print("\nPART 4  lag alone on a mission, noise switched off")
sig, bias = dict(R.SENSOR_SIGMA), dict(R.SENSOR_BIAS_SIGMA)
R.SENSOR_SIGMA.clear(); R.SENSOR_BIAS_SIGMA.clear()
from engine_model.stage5_simulation_pipeline import run_mission, run_mission_realistic
from generate_stage7_abnormal_dataset import build_config
cfg = build_config("RAPID_THROTTLE", "VERIFY_RT_0001", 424242)
ideal, lagged = run_mission(cfg), run_mission_realistic(cfg, engine_seed=1)
R.SENSOR_SIGMA.update(sig); R.SENSOR_BIAS_SIGMA.update(bias)
def mx(rows, name):
    return max(abs(float(getattr(rows[i], name)) - float(getattr(rows[i-1], name)))
               for i in range(1, len(rows)))
print("  %-18s %10s %10s" % ("channel", "ideal", "lagged"))
for ch in ("coolant_temp_C", "oil_temperature_C", "EGT_mean_C", "p_plenum_bar"):
    print("  %-18s %10.4f %10.4f" % (ch, mx(ideal, ch), mx(lagged, ch)))
print("  (lagged must be <= ideal on every row)")
