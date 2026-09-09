import cProfile, pstats, io, time
from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput
from engine_model.stage5_simulation_pipeline import run_mission_realistic
from generate_stage7_abnormal_dataset import build_config

t0 = time.perf_counter(); m = Stage13HybridEngineOutput(); ctor = time.perf_counter() - t0
print("constructor: %.3f s" % ctor)

t0 = time.perf_counter()
for _ in range(200):
    m.get_engine_state(5000.0, 84.5, 6000.0, 10.0)
per = (time.perf_counter() - t0) / 200
print("get_engine_state: %.2f ms per call  -> %.0f rows/s ceiling" % (per*1000, 1/per))

cfg = build_config("RAPID_THROTTLE", "PROF", 1)
pr = cProfile.Profile(); pr.enable()
run_mission_realistic(cfg, engine_seed=1)
pr.disable()
s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(18)
print("\n".join(s.getvalue().splitlines()[4:28]))
