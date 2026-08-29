"""
STAGE 6 - Healthy / Normal Dataset Generator

Generates the healthy baseline dataset from the validated Stage 5 pipeline.

Design:
    500 engine IDs
    6 mission types per engine
    3000 complete mission runs

Important:
    - Stage 1-5 production code is NOT modified.
    - One mission is generated at a time.
    - Each mission is written immediately to CSV.
    - Telemetry rows are not accumulated in RAM.
    - Engine IDs and mission IDs are unique.
    - Random seeds are deterministic and unique.
    - Stage 5's validated 1-second timestep is used.
    - No artificial engine-physics variation is injected here.
      That must be implemented at the model layer rather than by
      randomly changing telemetry after simulation.

Output:
    stage6_outputs/normal_healthy_dataset.csv

The resulting number of rows is determined by the complete mission
durations. It may be above or below exactly 2,000,000 rows.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository setup
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stage 5 imports
# ---------------------------------------------------------------------------

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

from engine_model.stage5_simulation_pipeline import (
    TELEMETRY_FIELDNAMES,
    run_mission,
)


# ---------------------------------------------------------------------------
# Dataset configuration
# ---------------------------------------------------------------------------

NUM_ENGINES = 500

TIMESTEP_S = 1.0

RANDOM_SEED_BASE = 1_000_000

OUTPUT_DIR = ROOT / "stage6_outputs"
OUTPUT_FILE = OUTPUT_DIR / "normal_healthy_dataset.csv"

# Set this to True if you want to start from zero.
# If False, an existing file is continued safely only if its structure
# matches this generator.
OVERWRITE_OUTPUT = True


# ---------------------------------------------------------------------------
# Mission builders
# ---------------------------------------------------------------------------

MISSION_BUILDERS = {
    MISSION_TYPE_NORMAL: build_normal_mission_config,
    MISSION_TYPE_HIGH_ALTITUDE: build_high_altitude_mission_config,
    MISSION_TYPE_ENDURANCE: build_endurance_mission_config,
    MISSION_TYPE_HOT_WEATHER: build_hot_weather_mission_config,
    MISSION_TYPE_HIGH_POWER: build_high_power_mission_config,
    MISSION_TYPE_RAPID_THROTTLE: build_rapid_throttle_mission_config,
}


MISSION_TYPES = (
    MISSION_TYPE_NORMAL,
    MISSION_TYPE_HIGH_ALTITUDE,
    MISSION_TYPE_ENDURANCE,
    MISSION_TYPE_HOT_WEATHER,
    MISSION_TYPE_HIGH_POWER,
    MISSION_TYPE_RAPID_THROTTLE,
)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def make_seed(engine_number: int, mission_number: int) -> int:
    """
    Generate a deterministic unique seed for every engine/mission pair.
    """
    return (
        RANDOM_SEED_BASE
        + engine_number * 100
        + mission_number
    )


def make_engine_id(engine_number: int) -> str:
    return f"ENG_{engine_number:04d}"


def make_mission_id(
    engine_number: int,
    mission_number: int,
    mission_type: str,
) -> str:
    return (
        f"eng_{engine_number:04d}_"
        f"mission_{mission_number:02d}_"
        f"{mission_type.lower()}"
    )


def build_config(
    mission_type: str,
    *,
    mission_id: str,
    random_seed: int,
):
    """
    Build the correct Stage 5 configuration.

    NORMAL is intentionally handled by its dedicated builder because
    its duration is derived from altitude/climb/descent settings.
    """

    builder = MISSION_BUILDERS[mission_type]

    return builder(
        mission_id=mission_id,
        timestep_s=TIMESTEP_S,
        random_seed=random_seed,
    )


def validate_rows(rows, mission_type: str, mission_id: str) -> None:
    """
    Lightweight validation before rows are committed to disk.

    This is intentionally not the full Stage 5 validation suite.
    It catches catastrophic generation problems without adding a
    second expensive simulation pass.
    """

    if not rows:
        raise RuntimeError(
            f"{mission_id}: Stage 5 returned zero rows."
        )

    first = rows[0]

    if first.time_s != 0.0:
        raise RuntimeError(
            f"{mission_id}: first timestamp is "
            f"{first.time_s}, expected 0.0."
        )

    previous_time = first.time_s

    for index, row in enumerate(rows):

        if row.mission_id != mission_id:
            raise RuntimeError(
                f"{mission_id}: mission_id mismatch at row {index}."
            )

        if row.mission_type != mission_type:
            raise RuntimeError(
                f"{mission_id}: mission_type mismatch at row {index}."
            )

        current_time = float(row.time_s)

        if index > 0:
            dt = current_time - previous_time

            if abs(dt - TIMESTEP_S) > 1e-9:
                raise RuntimeError(
                    f"{mission_id}: invalid timestep at row {index}: "
                    f"{dt} s."
                )

        previous_time = current_time


def write_rows(
    writer: csv.DictWriter,
    rows,
    engine_id: str,
) -> int:
    """
    Write one complete mission to disk immediately.

    Only the current mission's rows exist in memory.
    """

    count = 0

    for row in rows:
        data = row.to_dict()

        # Stage 6 dataset identity.
        data["engine_id"] = engine_id

        writer.writerow(data)

        count += 1

    return count


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def main() -> None:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_FILE.exists():

        if OVERWRITE_OUTPUT:
            print(
                f"Existing output will be replaced:\n"
                f"{OUTPUT_FILE}"
            )
            OUTPUT_FILE.unlink()

        else:
            raise RuntimeError(
                f"Output already exists:\n{OUTPUT_FILE}\n"
                f"Set OVERWRITE_OUTPUT=True to regenerate."
            )

    fieldnames = [
        "engine_id",
        *TELEMETRY_FIELDNAMES,
    ]

    total_missions = NUM_ENGINES * len(MISSION_TYPES)

    total_rows = 0
    completed_missions = 0
    failed_missions = 0

    dataset_start = time.perf_counter()

    print("=" * 100)
    print("STAGE 6 - HEALTHY DATASET GENERATION")
    print("=" * 100)
    print(f"Engines              : {NUM_ENGINES}")
    print(f"Mission types        : {len(MISSION_TYPES)}")
    print(f"Missions / engine    : {len(MISSION_TYPES)}")
    print(f"Total missions       : {total_missions}")
    print(f"Timestep             : {TIMESTEP_S} s")
    print(f"Output               : {OUTPUT_FILE}")
    print()
    print("Memory strategy      : one mission at a time")
    print("Engine physics       : current validated Stage 5 model")
    print("Virtual variation    : NOT injected yet")
    print()
    print("Generation started...")
    print()

    with OUTPUT_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as fh:

        writer = csv.DictWriter(
            fh,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        # ---------------------------------------------------------------
        # Engine loop
        # ---------------------------------------------------------------

        for engine_number in range(
            1,
            NUM_ENGINES + 1,
        ):

            engine_id = make_engine_id(engine_number)

            engine_start = time.perf_counter()
            engine_rows = 0

            print(
                "-" * 100
            )

            print(
                f"ENGINE {engine_number}/{NUM_ENGINES} "
                f"({engine_id})"
            )

            # -----------------------------------------------------------
            # Mission loop
            # -----------------------------------------------------------

            for mission_number, mission_type in enumerate(
                MISSION_TYPES,
                start=1,
            ):

                mission_id = make_mission_id(
                    engine_number,
                    mission_number,
                    mission_type,
                )

                seed = make_seed(
                    engine_number,
                    mission_number,
                )

                mission_start = time.perf_counter()

                print(
                    f"  [{completed_missions + 1:04d}/"
                    f"{total_missions:04d}] "
                    f"{mission_type:<18} "
                    f"seed={seed}",
                    flush=True,
                )

                try:

                    # ---------------------------------------------------
                    # Build validated Stage 5 configuration.
                    # ---------------------------------------------------

                    config = build_config(
                        mission_type,
                        mission_id=mission_id,
                        random_seed=seed,
                    )

                    # ---------------------------------------------------
                    # Run ONE complete mission.
                    #
                    # Important:
                    # run_mission() returns a list for this mission only.
                    # It is written immediately and then discarded.
                    # ---------------------------------------------------

                    rows = run_mission(config)

                    # ---------------------------------------------------
                    # Lightweight integrity checks.
                    # ---------------------------------------------------

                    validate_rows(
                        rows,
                        mission_type,
                        mission_id,
                    )

                    # ---------------------------------------------------
                    # Write immediately to CSV.
                    # ---------------------------------------------------

                    row_count = write_rows(
                        writer,
                        rows,
                        engine_id,
                    )

                    # Flush after every mission so progress is safely
                    # committed to disk instead of remaining buffered.
                    fh.flush()

                    elapsed = (
                        time.perf_counter()
                        - mission_start
                    )

                    total_rows += row_count
                    engine_rows += row_count
                    completed_missions += 1

                    print(
                        f"      PASS | "
                        f"{row_count:,} rows | "
                        f"{elapsed:.2f} s",
                        flush=True,
                    )

                    # Explicitly release the mission list before the
                    # next mission.
                    del rows

                except Exception as exc:

                    failed_missions += 1

                    print(
                        f"      FAIL | "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )

                    # Stop immediately rather than producing a partially
                    # corrupted scientific dataset.
                    raise RuntimeError(
                        f"Dataset generation stopped at "
                        f"{engine_id} / {mission_id}."
                    ) from exc

            # -----------------------------------------------------------
            # Engine summary
            # -----------------------------------------------------------

            engine_elapsed = (
                time.perf_counter()
                - engine_start
            )

            print(
                f"  ENGINE COMPLETE | "
                f"rows={engine_rows:,} | "
                f"time={engine_elapsed:.2f} s",
                flush=True,
            )

            # -----------------------------------------------------------
            # Overall progress
            # -----------------------------------------------------------

            dataset_elapsed = (
                time.perf_counter()
                - dataset_start
            )

            average_mission_time = (
                dataset_elapsed
                / completed_missions
            )

            remaining_missions = (
                total_missions
                - completed_missions
            )

            estimated_remaining = (
                average_mission_time
                * remaining_missions
            )

            print(
                f"  TOTAL PROGRESS | "
                f"missions={completed_missions}/"
                f"{total_missions} | "
                f"rows={total_rows:,} | "
                f"elapsed={dataset_elapsed / 3600:.2f} h | "
                f"ETA={estimated_remaining / 3600:.2f} h",
                flush=True,
            )

    # -----------------------------------------------------------------------
    # Final report
    # -----------------------------------------------------------------------

    total_elapsed = (
        time.perf_counter()
        - dataset_start
    )

    print()
    print("=" * 100)
    print("STAGE 6 DATASET GENERATION COMPLETE")
    print("=" * 100)

    print(f"Engines generated     : {NUM_ENGINES}")
    print(f"Mission types         : {len(MISSION_TYPES)}")
    print(f"Missions completed    : {completed_missions}")
    print(f"Missions failed       : {failed_missions}")
    print(f"Rows generated        : {total_rows:,}")

    print(
        f"Runtime               : "
        f"{total_elapsed:.2f} seconds"
    )

    print(
        f"Runtime               : "
        f"{total_elapsed / 60:.2f} minutes"
    )

    print(
        f"Runtime               : "
        f"{total_elapsed / 3600:.2f} hours"
    )

    if completed_missions:
        print(
            f"Average rows/mission  : "
            f"{total_rows / completed_missions:.1f}"
        )

        print(
            f"Average time/mission  : "
            f"{total_elapsed / completed_missions:.2f} s"
        )

    print()
    print(f"CSV output:")
    print(OUTPUT_FILE)

    print()
    print("STATUS: PASS")
    print("=" * 100)


if __name__ == "__main__":
    main()