"""Generate a 1,000-row healthy Stage 5 reference dataset."""

from pathlib import Path
import csv

from engine_model.stage5_mission_config import build_normal_mission_config
from engine_model.stage5_simulation_pipeline import (
    run_mission,
    TELEMETRY_FIELDNAMES,
)


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "stage5_outputs" / "temp_data.csv"

ENGINE_ID = "ENG_0001"
MISSION_ID = "temp_mission_001"
TIMESTEP_S = 1.0
RANDOM_SEED = 42
 


def main() -> None:
    # One virtual engine, one complete NORMAL mission.
    #
    # The altitude and cruise duration are selected so that the
    # complete mission is approximately 1000 seconds at a 1-second
    # timestep while retaining all mission phases.
    config = build_normal_mission_config(
        mission_id=MISSION_ID,
        timestep_s=TIMESTEP_S,
        initial_altitude_ft=0.0,
        target_altitude_ft=5000.0,
        climb_rate_fpm=1200.0,
        descent_rate_fpm=1000.0,
        cruise_duration_s=410.0,
        random_seed=RANDOM_SEED,
    )

    rows = run_mission(config)

    

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["engine_id"] + list(TELEMETRY_FIELDNAMES)

    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            data = row.to_dict()
            data["engine_id"] = ENGINE_ID
            writer.writerow(data)

    print(f"Generated: {OUTPUT}")
    print(f"Rows: {len(rows)}")
    print(f"Engine: {ENGINE_ID}")
    print(f"Mission: {config.mission_id}")
    print(f"Mission type: {config.mission_type}")
    print(f"Timestep: {config.timestep_s} s")
    print(f"Total duration: {config.total_duration_s:.2f} s")


if __name__ == "__main__":
    main()