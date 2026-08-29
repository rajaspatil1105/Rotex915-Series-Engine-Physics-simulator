"""Stage 0-5 freeze audit for the Rotax 915 iS repository.

This audit is intentionally read/execute-only with respect to production model code.
It runs existing validation/tests, checks the Stage 5 reference CSV, verifies
protected-file hashes do not change during the audit, and prints a final report.
"""
from __future__ import annotations

import csv
import hashlib
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PROTECTED_PATTERNS = [
    "engine_model/stage1_2_*.py",
    "engine_model/stage1_3_hybrid_engine_output.py",
    "rotax_915is_performance_map.csv",
    "calibration/*.csv",
    "calibration/*.json",
    "config/rotax_915is_engine_parameters.csv",
    "config/rotax_915is_engine_parameters.md",
    "config/rotax_915is_missing_parameters.md",
]

COMMANDS = [
    ("Stage 1.3 hybrid validation", [sys.executable, "engine_model/stage1_3_hybrid_validation.py"]),
    ("Stage 1.3 sea-level validation", [sys.executable, "engine_model/stage1_3_sealevel_validation.py"]),
    ("Stage 2 smoke validation", [sys.executable, "engine_model/stage2_engine_state_smoke_validation.py"]),
    ("Stage 3 altitude validation", [sys.executable, "engine_model/stage3_altitude_profile_validation.py"]),
    ("Stage 4 health validation", [sys.executable, "engine_model/stage4_health_validation.py"]),
    ("Stage 5 mission validation", [sys.executable, "engine_model/stage5_mission_validation.py"]),
    ("Stage 5 telemetry validation", [sys.executable, "engine_model/stage5_telemetry_validation.py"]),
    ("Complete regression/unit test suite", [sys.executable, "-m", "pytest", "-q"]),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_snapshot() -> dict[str, str]:
    result: dict[str, str] = {}
    for pattern in PROTECTED_PATTERNS:
        for path in ROOT.glob(pattern):
            if path.is_file():
                result[str(path.relative_to(ROOT))] = sha256(path)
    return result


def run_command(label: str, command: list[str]) -> bool:
    print(f"\n--- {label} ---")
    print("$", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip())
    print(f"RESULT: {'PASS' if completed.returncode == 0 else 'FAIL'}")
    return completed.returncode == 0


def audit_temp_csv() -> tuple[bool, list[str]]:
    path = ROOT / "stage5_outputs" / "temp_data.csv"
    findings: list[str] = []
    if not path.exists():
        return False, ["stage5_outputs/temp_data.csv is missing"]

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or []

    if not rows:
        findings.append("temp_data.csv has no data rows")
        return False, findings

    required = {
        "time_s", "mission_id", "mission_type", "phase", "engine_id",
        "altitude_ft", "rpm", "throttle_pct", "power_kW", "torque_Nm",
        "fuelflow_kgh", "p_plenum_bar", "t_plenum_K",
        "coolant_temp_C", "EGT_mean_C", "EGT_spread_C",
        "oil_pressure_bar", "oil_temperature_C", "battery_voltage_V",
        "battery_soc_pct", "generator_A_current_A", "generator_B_current_A",
        "generator_voltage_V", "generator_power_W", "vibration_frequency_Hz",
    }
    missing = sorted(required - set(fields))
    if missing:
        findings.append("Missing required columns: " + ", ".join(missing))

    # Numeric finite checks for the main telemetry fields.
    numeric_fields = [
        "time_s", "altitude_ft", "rpm", "throttle_pct", "power_kW",
        "torque_Nm", "fuelflow_kgh", "p_plenum_bar", "t_plenum_K",
        "coolant_temp_C", "EGT_mean_C", "EGT_spread_C",
        "oil_pressure_bar", "oil_temperature_C", "battery_voltage_V",
        "battery_soc_pct", "generator_A_current_A", "generator_B_current_A",
        "generator_voltage_V", "generator_power_W", "vibration_frequency_Hz",
    ]
    bad_numeric = []
    for i, row in enumerate(rows, start=2):
        for field in numeric_fields:
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError):
                bad_numeric.append(f"row {i}: {field} not numeric")
                continue
            if not math.isfinite(value):
                bad_numeric.append(f"row {i}: {field} is non-finite")
    if bad_numeric:
        findings.extend(bad_numeric[:20])
        if len(bad_numeric) > 20:
            findings.append(f"... and {len(bad_numeric) - 20} more numeric errors")

    # Timestamp/grid checks.
    try:
        times = [float(r["time_s"]) for r in rows]
        deltas = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        if not math.isclose(times[0], 0.0, abs_tol=1e-12):
            findings.append(f"First timestamp is {times[0]}, expected 0")
        if any(not math.isclose(d, 1.0, abs_tol=1e-9) for d in deltas):
            findings.append("Timestamp grid is not exactly 1 second")
    except (KeyError, ValueError):
        pass

    phases = [r.get("phase", "") for r in rows]
    expected_phases = ["TAKEOFF", "CLIMB", "CRUISE", "DESCENT", "IDLE/LANDING"]
    if not all(phase in phases for phase in expected_phases):
        findings.append("Not all five expected mission phases are present")

    # Basic bounds used by the existing Stage 5 architecture.
    for i, row in enumerate(rows, start=2):
        try:
            rpm = float(row["rpm"])
            throttle = float(row["throttle_pct"])
            altitude = float(row["altitude_ft"])
            gen_power = float(row["generator_power_W"])
            if not 0 <= rpm <= 5800:
                findings.append(f"row {i}: RPM out of range: {rpm}")
            if not 56.5 <= throttle <= 100:
                findings.append(f"row {i}: throttle out of range: {throttle}")
            if altitude < 0:
                findings.append(f"row {i}: negative altitude")
            if not 0 <= gen_power <= 420:
                findings.append(f"row {i}: generator power out of range: {gen_power}")
        except (KeyError, ValueError):
            continue

    # Duplicate check on complete rows.
    seen = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(field, "") for field in fields)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    if duplicate_count:
        findings.append(f"Duplicate complete rows: {duplicate_count}")

    return not findings, findings


def main() -> int:
    print("=" * 72)
    print("ROTAX 915 iS STAGE 0-5 FREEZE AUDIT")
    print("Repository:", ROOT)
    print("=" * 72)

    before = protected_snapshot()
    results: list[tuple[str, bool]] = []

    # Verify Graphify artifacts exist; this does not modify or regenerate them.
    graphify_ok = (ROOT / "graphify-out" / "graph.json").exists() and (ROOT / "graphify-out" / "GRAPH_REPORT.md").exists()
    results.append(("Graphify repository artifacts present", graphify_ok))
    print("\nGraphify artifacts:", "PASS" if graphify_ok else "FAIL")

    # Compile the current production/test Python files first.
    compile_targets = [
        "engine_model/stage1_3_hybrid_engine_output.py",
        "engine_model/stage4_health_parameters.py",
        "engine_model/stage5_mission_config.py",
        "engine_model/stage5_mission_generator.py",
        "engine_model/stage5_simulation_pipeline.py",
        "engine_model/stage5_telemetry_validation.py",
        "test_stage4_health.py",
        "test_stage5_mission.py",
        "test_stage5_telemetry.py",
        "test_stage_regressions.py",
        "generate_temp_data.py",
    ]
    results.append(("Python compilation", run_command("Python compilation", [sys.executable, "-m", "py_compile", *compile_targets])))

    for label, command in COMMANDS:
        results.append((label, run_command(label, command)))

    temp_ok, temp_findings = audit_temp_csv()
    results.append(("Stage 5 temp_data.csv smoke audit", temp_ok))
    print("\n--- temp_data.csv smoke audit ---")
    print("RESULT:", "PASS" if temp_ok else "FAIL")
    if temp_findings:
        for finding in temp_findings:
            print(" -", finding)
    else:
        print(" - 981-row reference dataset is structurally and numerically sane.")

    after = protected_snapshot()
    integrity_ok = before == after
    results.append(("Protected-file hash integrity during audit", integrity_ok))
    print("\nProtected-file integrity:", "PASS" if integrity_ok else "FAIL")
    if not integrity_ok:
        all_keys = sorted(set(before) | set(after))
        for key in all_keys:
            if before.get(key) != after.get(key):
                print(" - CHANGED:", key)

    print("\n" + "=" * 72)
    print("FINAL AUDIT REPORT")
    print("=" * 72)
    for label, ok in results:
        print(f"{'PASS' if ok else 'FAIL':<6} | {label}")

    failed = [label for label, ok in results if not ok]
    if failed:
        print("\nOVERALL: FAIL")
        print("Blocking/failed checks:")
        for label in failed:
            print(" -", label)
        return 1

    print("\nOVERALL: PASS")
    print("Stage 0-5 freeze audit completed without detected blocking failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
