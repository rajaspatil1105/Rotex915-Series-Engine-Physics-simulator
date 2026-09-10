import pandas as pd
f = "stage6_outputs/normal_healthy_dataset.csv"
cols = ["power_kW","rpm","throttle_pct","coolant_temp_C","oil_temperature_C",
        "EGT_mean_C","EGT_spread_C","fuelflow_kgh"]
bins = [0,20,40,60,80,95,200]
acc, pmax = {}, 0.0
for ch in pd.read_csv(f, usecols=cols, chunksize=500000):
    pmax = max(pmax, float(ch.power_kW.max()))
    for k, g in ch.groupby(pd.cut(ch.power_kW, bins), observed=True):
        a = acc.setdefault(str(k), [0]+[0.0]*7)
        a[0] += len(g)
        a[1] += g.EGT_mean_C.sum();   a[2] += g.EGT_spread_C.sum()
        a[3] += g.coolant_temp_C.sum(); a[4] += g.oil_temperature_C.sum()
        a[5] += g.rpm.sum();          a[6] += g.fuelflow_kgh.sum()
        a[7] += g.power_kW.sum()
tot = sum(a[0] for a in acc.values())
print(f"{'power kW':<12}{'rows':>9}{'%':>6}{'EGT':>7}{'sprd':>6}{'cool':>7}{'oil':>7}{'rpm':>7}{'bsfc':>7}")
for k in sorted(acc, key=lambda s: float(s.split(',')[0][1:])):
    n,e,sp,c,o,rp,fu,pw = acc[k]
    print(f"{k:<12}{n:>9}{100*n/tot:6.1f}{e/n:7.0f}{sp/n:6.0f}{c/n:7.1f}{o/n:7.1f}{rp/n:7.0f}{fu/pw*1000:7.0f}")
print("max power seen %.1f kW   (rated 105)" % pmax)
