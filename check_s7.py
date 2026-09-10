import pandas as pd, collections
c = collections.Counter()
faults = collections.Counter()
cols = ["engine_id"]
hdr = list(pd.read_csv("stage7_outputs/abnormal_fault_dataset.csv", nrows=0).columns)
fc = next((x for x in hdr if "fault" in x.lower() and "type" in x.lower()), None)
if fc: cols.append(fc)
for ch in pd.read_csv("stage7_outputs/abnormal_fault_dataset.csv", usecols=cols, chunksize=500000):
    c.update(ch.engine_id.value_counts().to_dict())
    if fc: faults.update(ch[fc].value_counts().to_dict())
print("engines in CSV:", len(c))
miss = [f"ENG_{n:04d}" for n in range(1,41) if f"ENG_{n:04d}" not in c]
print("MISSING:", miss if miss else "none - safe to build")
print("rows/engine  min", min(c.values()), " max", max(c.values()))
if fc:
    print("\nfault balance:")
    for k,v in faults.most_common(): print(f"  {k:<32}{v:>10,}")
