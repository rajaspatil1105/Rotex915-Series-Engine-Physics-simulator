import csv, statistics, glob
path = (glob.glob("rotax_915is_performance_map.csv") + glob.glob("**/rotax_915is_performance_map.csv", recursive=True))[0]
rows = list(csv.DictReader(open(path, newline="")))
print("file:", path, "rows:", len(rows))
b = []
for r in rows:
    try:
        p = float(r["power_kW"]); f = float(r["fuelflow_kgh"])
    except (KeyError, ValueError):
        continue
    if p > 5.0:
        b.append((f * 1000.0 / p, float(r["rpm"]), float(r["throttle_pct"]), float(r["alt_ft"]), p, f))
b.sort()
print("bsfc g/kWh  min %.1f  median %.1f  max %.1f" % (b[0][0], statistics.median(x[0] for x in b), b[-1][0]))
print("count below 230 g/kWh (impossible):", sum(1 for x in b if x[0] < 230.0), "of", len(b))
print("\nten leanest points  bsfc / rpm / thr / alt / kW / kg-h")
for x in b[:10]:
    print("  %8.1f %7.0f %6.1f %8.0f %7.2f %6.2f" % x)
