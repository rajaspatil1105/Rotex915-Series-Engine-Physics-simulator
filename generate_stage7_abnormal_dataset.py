"""
STAGE 7 - Abnormal/Fault Dataset Generator

Stage 5 is intentionally left unchanged.

This generator:
1. Builds a normal Stage-5 mission.
2. Applies one Stage-7 fault model.
3. Writes the abnormal telemetry with fault metadata.
4. Checkpoints after every mission.
5. Logs failed missions separately and continues.

Default design is deliberately configurable. Start with a small pilot before
committing to the full 250-engine production run.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from engine_model.stage5_mission_config import (
    MISSION_TYPE_NORMAL,
    MISSION_TYPE_HIGH_ALTITUDE,
    MISSION_TYPE_ENDURANCE,
    MISSION_TYPE_HOT_WEATHER,
    MISSION_TYPE_HIGH_POWER,
    MISSION_TYPE_RAPID_THROTTLE,
    build_normal_mission_config,
    build_high_altitude_mission_config,
    build_endurance_mission_config,
    build_hot_weather_mission_config,
    build_high_power_mission_config,
    build_rapid_throttle_mission_config,
)
from engine_model.stage5_simulation_pipeline import TELEMETRY_FIELDNAMES, run_mission
from engine_model.stage7_fault_config import ACTIVE_FAULTS, MODEL_VERSION
from engine_model.stage7_fault_models import apply_fault


# ---------------------------------------------------------------------------
# Production configuration
# ---------------------------------------------------------------------------

NUM_ENGINES = 250
TIMESTEP_S = 1.0
RANDOM_SEED_BASE = 2_000_000

# Pilot first. Set to 250 only after validation.
ENGINE_START = 1
ENGINE_END = NUM_ENGINES

# One faulted mission per selected fault/severity/mission combination.
SEVERITIES = ("mild", "moderate", "severe")

OUTPUT_DIR = Path(__file__).resolve().parent / "stage7_outputs"
OUTPUT_FILE = OUTPUT_DIR / "abnormal_fault_dataset.csv"
FAILED_FILE = OUTPUT_DIR / "failed_missions.csv"
CHECKPOINT_FILE = OUTPUT_DIR / "stage7_checkpoint.json"

MISSION_TYPES = (
    MISSION_TYPE_NORMAL,
    MISSION_TYPE_HIGH_ALTITUDE,
    MISSION_TYPE_ENDURANCE,
    MISSION_TYPE_HOT_WEATHER,
    MISSION_TYPE_HIGH_POWER,
    MISSION_TYPE_RAPID_THROTTLE,
)

MISSION_BUILDERS = {
    MISSION_TYPE_NORMAL: build_normal_mission_config,
    MISSION_TYPE_HIGH_ALTITUDE: build_high_altitude_mission_config,
    MISSION_TYPE_ENDURANCE: build_endurance_mission_config,
    MISSION_TYPE_HOT_WEATHER: build_hot_weather_mission_config,
    MISSION_TYPE_HIGH_POWER: build_high_power_mission_config,
    MISSION_TYPE_RAPID_THROTTLE: build_rapid_throttle_mission_config,
}

EXTRA_FIELDS = [
    "engine_id",
    "fault_present",
    "fault_type",
    "fault_category",
    "fault_severity",
    "fault_start_time_s",
    "fault_end_time_s",
    "fault_envelope",
    "fuel_pressure_bar",
    "limit_exceeded",
    "limit_parameter",
    "limit_value",
    "true_sensor_value",
    "measured_sensor_value",
]

FIELDNAMES = EXTRA_FIELDS + [
    field for field in TELEMETRY_FIELDNAMES if field != "engine_id"
]


def make_seed(engine_number: int, mission_number: int, fault_index: int, severity_index: int) -> int:
    return (
        RANDOM_SEED_BASE
        + engine_number * 10_000
        + mission_number * 100
        + fault_index * 10
        + severity_index
    )


def make_engine_id(engine_number: int) -> str:
    return f"ENG_{engine_number:04d}"


def make_mission_id(engine_number: int, mission_number: int, mission_type: str) -> str:
    return (
        f"eng_{engine_number:04d}_"
        f"stage7_mission_{mission_number:02d}_"
        f"{mission_type.lower()}"
    )


def make_fault_mission_id(
    engine_number: int,
    mission_number: int,
    mission_type: str,
    fault_type: str,
    severity: str,
) -> str:
    return (
        f"eng_{engine_number:04d}_"
        f"stage7_mission_{mission_number:02d}_"
        f"{mission_type.lower()}_"
        f"{fault_type}_"
        f"{severity}"
    )


def build_config(mission_type: str, mission_id: str, seed: int):
    return MISSION_BUILDERS[mission_type](
        mission_id=mission_id,
        timestep_s=TIMESTEP_S,
        random_seed=seed,
    )


def load_checkpoint() -> dict:
    if not CHECKPOINT_FILE.exists():
        return {"completed": [], "failed": [], "total_rows": 0}

    return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))


def save_checkpoint(state: dict) -> None:
    tmp = CHECKPOINT_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(CHECKPOINT_FILE)


def append_failure(
    failure_writer: csv.DictWriter,
    *,
    engine_id: str,
    mission_id: str,
    mission_type: str,
    fault_type: str,
    severity: str,
    error: Exception,
) -> None:
    failure_writer.writerow(
        {
            "engine_id": engine_id,
            "mission_id": mission_id,
            "mission_type": mission_type,
            "fault_type": fault_type,
            "severity": severity,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    checkpoint = load_checkpoint()
    completed = set(checkpoint.get("completed", []))
    failed = set(checkpoint.get("failed", []))
    total_rows = int(checkpoint.get("total_rows", 0))

    total_missions = (
        (ENGINE_END - ENGINE_START + 1)
        * len(MISSION_TYPES)
        * len(ACTIVE_FAULTS)
        * len(SEVERITIES)
    )

    failure_fields = [
        "engine_id",
        "mission_id",
        "mission_type",
        "fault_type",
        "severity",
        "error_type",
        "error_message",
    ]

    output_exists = OUTPUT_FILE.exists()
    failure_exists = FAILED_FILE.exists()

    with OUTPUT_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as output_fh, FAILED_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as failure_fh:

        writer = csv.DictWriter(output_fh, fieldnames=FIELDNAMES)
        failure_writer = csv.DictWriter(failure_fh, fieldnames=failure_fields)

        if not output_exists:
            writer.writeheader()
            output_fh.flush()

        if not failure_exists:
            failure_writer.writeheader()
            failure_fh.flush()

        processed = len(completed) + len(failed)
        start_time = time.perf_counter()

        print("=" * 110)
        print("STAGE 7 — CHECKPOINTED ABNORMAL DATASET GENERATION")
        print("=" * 110)
        print(f"Engines              : {ENGINE_START}-{ENGINE_END}")
        print(f"Mission types        : {len(MISSION_TYPES)}")
        print(f"Fault types          : {len(ACTIVE_FAULTS)}")
        print(f"Severity levels      : {len(SEVERITIES)}")
        print(f"Total missions       : {total_missions}")
        print(f"Completed            : {len(completed)}")
        print(f"Failed               : {len(failed)}")
        print(f"Rows                 : {total_rows:,}")
        print(f"Checkpoint            : AFTER EVERY MISSION")
        print(f"Model version         : {MODEL_VERSION}")
        print(f"Output                : {OUTPUT_FILE}")
        print(f"Failures              : {FAILED_FILE}")
        print(f"Checkpoint            : {CHECKPOINT_FILE}")
        print("=" * 110)

        for engine_number in range(ENGINE_START, ENGINE_END + 1):
            engine_id = make_engine_id(engine_number)

            for mission_number, mission_type in enumerate(MISSION_TYPES, start=1):
                for fault_index, fault_type in enumerate(ACTIVE_FAULTS):
                    for severity_index, severity in enumerate(SEVERITIES):
                        mission_id = make_fault_mission_id(
                            engine_number,
                            mission_number,
                            mission_type,
                            fault_type,
                            severity,
                        )

                        if mission_id in completed or mission_id in failed:
                            continue

                        seed = make_seed(
                            engine_number,
                            mission_number,
                            fault_index,
                            severity_index,
                        )

                        started = time.perf_counter()

                        try:
                            # Healthy Stage-5 mission first.
                            config = build_config(
                                mission_type,
                                mission_id=mission_id,
                                seed=seed,
                            )
                            healthy_rows = run_mission(config)

                            # Apply Stage-7 abnormal state.
                            abnormal_rows = apply_fault(
                                healthy_rows,
                                engine_id=engine_id,
                                fault_type=fault_type,
                                severity=severity,
                                seed=seed,
                            )

                            for row in abnormal_rows:
                                writer.writerow(row)

                            output_fh.flush()

                            completed.add(mission_id)
                            total_rows += len(abnormal_rows)

                            checkpoint["completed"] = sorted(completed)
                            checkpoint["failed"] = sorted(failed)
                            checkpoint["total_rows"] = total_rows
                            save_checkpoint(checkpoint)

                            elapsed = time.perf_counter() - started
                            processed += 1

                            remaining = total_missions - processed
                            average = (
                                (time.perf_counter() - start_time) / processed
                            )
                            eta_h = average * remaining / 3600.0

                            print(
                                f"[{processed:05d}/{total_missions:05d}] "
                                f"{engine_id} | {mission_type:<18} | "
                                f"{fault_type:<24} | {severity:<8} | "
                                f"ROWS={len(abnormal_rows):,} | "
                                f"TOTAL_ROWS={total_rows:,} | "
                                f"TIME={elapsed:.2f}s | "
                                f"FAILED={len(failed)} | "
                                f"CHECKPOINT=YES | "
                                f"ETA={eta_h:.2f}h",
                                flush=True,
                            )

                        except Exception as exc:
                            failed.add(mission_id)
                            append_failure(
                                failure_writer,
                                engine_id=engine_id,
                                mission_id=mission_id,
                                mission_type=mission_type,
                                fault_type=fault_type,
                                severity=severity,
                                error=exc,
                            )
                            failure_fh.flush()

                            checkpoint["completed"] = sorted(completed)
                            checkpoint["failed"] = sorted(failed)
                            checkpoint["total_rows"] = total_rows
                            save_checkpoint(checkpoint)

                            processed += 1

                            print(
                                f"[{processed:05d}/{total_missions:05d}] "
                                f"{engine_id} | {mission_type:<18} | "
                                f"{fault_type:<24} | {severity:<8} | "
                                f"ROWS=0 | TOTAL_ROWS={total_rows:,} | "
                                f"FAILED={len(failed)} | "
                                f"CHECKPOINT=YES | "
                                f"ERROR={type(exc).__name__}",
                                flush=True,
                            )

        print()
        print("=" * 110)
        print("STAGE 7 COMPLETE")
        print("=" * 110)
        print(f"Completed missions : {len(completed):,}")
        print(f"Failed missions    : {len(failed):,}")
        print(f"Rows generated     : {total_rows:,}")
        print(f"Output             : {OUTPUT_FILE}")







if __name__ == "__main__":
    main()
