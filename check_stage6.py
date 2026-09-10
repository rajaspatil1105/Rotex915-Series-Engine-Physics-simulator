import pandas as pd

hdr = list(pd.read_csv("stage6_outputs/normal_healthy_dataset.csv", nrows=0).columns)
print("COLUMNS (", len(hdr), ")")
for i in range(0, len(hdr), 4):
    print("   " + "  ".join(f"{c:<24}" for c in hdr[i:i+4]))

def pick(*cands):
    for c in cands:
        if c in hdr:
            return c
    low = {h.lower(): h for h in hdr}
    for c in cands:
        for k, h in low.items():
            if c.lower().split("_")[0] in k:
                return h
    raise SystemExit("cannot find column for " + cands[0])

EID = pick("engine_id")
THR = pick("throttle_percent", "throttle_pct", "throttle", "throttle_position")
COOL = pick("coolant_temp_C", "coolant_temperature_C", "coolant")
OIL = pick("oil_temperature_C", "oil_temp_C")
EGT = pick("EGT_mean_C", "egt_mean_C", "EGT_avg_C", "EGT1_C")
print(f"\nusing: {THR} | {COOL} | {OIL} | {EGT}\n")

cols = [EID, THR, COOL, OIL, EGT]
agg = {}
for ch in pd.read_csv("stage6_outputs/normal_healthy_dataset.csv", usecols=cols, chunksize=500000):
    ch = ch[ch[THR] > 70]
    for eid, g in ch.groupby(EID):
        a = agg.setdefault(eid, [0, 0.0, 0.0, 0.0])
        a[0] += len(g); a[1] += g[COOL].sum(); a[2] += g[OIL].sum(); a[3] += g[EGT].sum()

ids = sorted(agg)
print("engines:", len(ids))
print(f"{'engine':<12}{'coolant':>9}{'oil':>9}{'EGT':>9}")
for eid in ids[:3] + ids[len(ids)//2-1:len(ids)//2+2] + ids[-3:]:
    n, c, o, e = agg[eid]
    print(f"{eid:<12}{c/n:9.1f}{o/n:9.1f}{e/n:9.1f}")

tn = sum(a[0] for a in agg.values())
allc = sum(a[1] for a in agg.values())/tn
allo = sum(a[2] for a in agg.values())/tn
alle = sum(a[3] for a in agg.values())/tn
print(f"\nfleet mean  coolant {allc:.1f}  oil {allo:.1f}  EGT {alle:.1f}  (rows>70%% thr: {tn})")
print("PASS" if 85 <= allc <= 100 and 700 <= alle <= 820 else "FAIL - old-formula rows present")
