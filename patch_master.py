from pathlib import Path
p = Path("build_master_dataset.py")
t = p.read_text(encoding="utf-8")

R = [
 ("ABNORMAL_ENGINE_MAX = 10",
  "ABNORMAL_ENGINE_MAX = 40"),
 ("if len(abnormal_engines) != 10:",
  "if len(abnormal_engines) != ABNORMAL_ENGINE_MAX:"),
 ('f"Expected 10 abnormal engines, "',
  'f"Expected {ABNORMAL_ENGINE_MAX} abnormal engines, "'),
 ('"ENG_0001 through ENG_0010."',
  'f"ENG_0001 through ENG_{ABNORMAL_ENGINE_MAX:04d}."'),
 ('"Abnormal engines: ENG_0001 -> ENG_0010"',
  'f"Abnormal engines: ENG_0001 -> ENG_{ABNORMAL_ENGINE_MAX:04d}"'),
 ("range(1, 261)",
  "range(1, ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX + 1)"),
 ('"ENG_0001 through ENG_0260."',
  'f"ENG_0001 through ENG_{ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX:04d}."'),
 ('"Abnormal engines: ENG_0251 -> ENG_0260"',
  'f"Abnormal engines: ENG_{ABNORMAL_TARGET_OFFSET + 1:04d} -> "\n        f"ENG_{ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX:04d}"'),
 ('"Unique engines  : 260"',
  'f"Unique engines  : {ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX}"'),
 ('"Engines : 260"',
  'f"Engines : {ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX}"'),
 ('"Abnormal: ENG_0251 -> ENG_0260"',
  'f"Abnormal: ENG_{ABNORMAL_TARGET_OFFSET + 1:04d} -> "\n        f"ENG_{ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX:04d}"'),
]

bad = []
for old, new in R:
    n = t.count(old)
    if n == 0:
        bad.append(f"NOT FOUND: {old}")
    else:
        t = t.replace(old, new)
        print(f"  {n}x  {old[:52]}")
if bad:
    print("\n".join(bad)); raise SystemExit("aborted, nothing written")

p.write_text(t, encoding="utf-8")
print("\nwritten")
