from rotax_reference_model_v2 import RotaxReferenceModel, COL_RPM, COL_THROTTLE, COL_ALT
import sys

csv_path = r"C:\Users\patil\OneDrive\Desktop\rotex data\rotax_915is_performance_map.csv"

try:
    ref = RotaxReferenceModel(csv_path)
    print("Model initialized successfully.")
except Exception as e:
    print("Model initialization failed:", type(e).__name__, e)
    sys.exit(1)

print('\nCoverage report:\n')
print(ref.coverage_report())

print('\nPressure/altitude diagnostic (first 10 rows):\n')
print(ref.pressure_altitude_report.head(10).to_string(index=False))

print('\nTemperature offset bands found:', sorted(ref.df['temp_offset_band'].unique().tolist()))

# Duplicate point summary
coords = [COL_RPM, COL_THROTTLE, COL_ALT, 'temp_offset_band']
orig_dup_count = ref.df.duplicated(subset=coords, keep=False).sum()
if hasattr(ref, '_df_model'):
    dedup_count = len(ref.df) - len(ref._df_model)
else:
    dedup_count = 0
print(f'Original duplicate rows (count, any): {orig_dup_count}, deduplicated rows: {dedup_count}')

# Example queries from the script
queries = [
    (5800, 100.0, 0, 0.0, 'validation'),
    (5200, 80.0, 10000, 15.0, 'validation'),
    (3000, 100.0, 22000, 45.0, 'boundary'),
]
for rpm, thr, alt, band, mode in queries:
    try:
        res = ref.query(rpm=rpm, throttle_pct=thr, alt_ft=alt, temp_offset_band=band, mode=mode)
        print(f'Query {rpm,thr,alt,band,mode} -> exact={res.exact} interpolated={res.interpolated} extrapolated={res.extrapolated} outputs=(power_kW={res.power_kW}, fuelflow_kgh={res.fuelflow_kgh})')
    except Exception as e:
        print(f'Query {rpm,thr,alt,band,mode} raised: {type(e).__name__}: {e}')

# Run a modest leave-one-out sample
try:
    loo = ref.leave_one_out_check(max_points=100)
    evaluated = loo[loo['status'] == 'evaluated']
    skipped = len(loo) - len(evaluated)
    print(f'Leave-one-out: evaluated={len(evaluated)}, skipped={skipped}, total_sampled={len(loo)}')
except Exception as e:
    print('Leave-one-out diagnostic failed:', type(e).__name__, e)
