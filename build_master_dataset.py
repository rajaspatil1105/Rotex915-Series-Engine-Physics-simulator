from pathlib import Path
import random
import csv
import sys

import numpy as np
import pandas as pd


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT = Path(__file__).resolve().parent

NORMAL_PATH = (
    PROJECT
    / "stage6_outputs"
    / "normal_healthy_merged.csv"
)

ABNORMAL_PATH = (
    PROJECT
    / "stage7_outputs"
    / "abnormal_fault_dataset.csv"
)

OUTPUT_DIR = PROJECT / "master_dataset"

OUTPUT_PATH = (
    OUTPUT_DIR
    / "master_dataset.csv"
)

# Temporary output used while building.
TEMP_PATH = (
    OUTPUT_DIR
    / "master_dataset.tmp.csv"
)


# ============================================================
# CONFIGURATION
# ============================================================

CHUNK_SIZE = 50_000

NORMAL_ENGINE_MIN = 1
NORMAL_ENGINE_MAX = 250

ABNORMAL_ENGINE_MIN = 1
ABNORMAL_ENGINE_MAX = 40

ABNORMAL_TARGET_OFFSET = 250


# ============================================================
# STAGE-7 FUEL PRESSURE
# ============================================================

FUEL_PRESSURE_NOMINAL_BAR = 3.0
FUEL_PRESSURE_MIN_BAR = 2.90
FUEL_PRESSURE_MAX_BAR = 3.10
FUEL_PRESSURE_SCATTER_BAR = 0.015


# ============================================================
# STAGE-7 EXTRA COLUMNS
# ============================================================

STAGE7_COLUMNS = [
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


# ============================================================
# EXPECTED FAULT TYPES
# ============================================================

EXPECTED_FAULT_TYPES = {
    "cooling_degradation",
    "fuel_pressure_deviation",
    "lubrication_degradation",
    "misfire",
    "sensor_drift",
}


EXPECTED_SEVERITIES = {
    "mild",
    "moderate",
    "severe",
}


# ============================================================
# HELPERS
# ============================================================

def section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def fail(message: str) -> None:
    raise RuntimeError(
        "\nMASTER DATASET BUILD FAILED:\n"
        + message
    )


def engine_number(engine_id: str) -> int:
    try:
        return int(engine_id.split("_")[1])
    except Exception:
        raise ValueError(
            f"Invalid engine_id: {engine_id}"
        )


def healthy_fuel_pressure(seed: int) -> float:
    """
    Stage-7 healthy fuel-pressure rule:

        3.0 + uniform(-0.015, +0.015)

    clamped to:

        2.90 - 3.10 bar

    Deterministic from the existing random_seed.
    """

    rng = random.Random(int(seed))

    value = (
        FUEL_PRESSURE_NOMINAL_BAR
        + rng.uniform(
            -FUEL_PRESSURE_SCATTER_BAR,
            FUEL_PRESSURE_SCATTER_BAR,
        )
    )

    return max(
        FUEL_PRESSURE_MIN_BAR,
        min(
            FUEL_PRESSURE_MAX_BAR,
            value,
        ),
    )


# ============================================================
# NORMAL DATA PREPARATION
# ============================================================

def prepare_normal(chunk: pd.DataFrame) -> pd.DataFrame:

    chunk = chunk.copy()

    # --------------------------------------------------------
    # Validate required columns
    # --------------------------------------------------------

    required = [
        "engine_id",
        "random_seed",
        "coolant_temp_C",
        "oil_temperature_C",
        "EGT_max_C",
        "EGT_spread_C",
        "fuelflow_kgh",
    ]

    missing = [
        c for c in required
        if c not in chunk.columns
    ]

    if missing:
        fail(
            "Normal dataset missing required columns:\n"
            + "\n".join(missing)
        )

    # --------------------------------------------------------
    # Healthy fault labels
    # --------------------------------------------------------

    chunk["fault_present"] = False
    chunk["fault_type"] = "healthy"
    chunk["fault_category"] = "none"
    chunk["fault_severity"] = "none"

    # --------------------------------------------------------
    # No active fault window
    # --------------------------------------------------------

    chunk["fault_start_time_s"] = np.nan
    chunk["fault_end_time_s"] = np.nan
    chunk["fault_envelope"] = 0.0

    # --------------------------------------------------------
    # Healthy fuel pressure
    # --------------------------------------------------------

    chunk["fuel_pressure_bar"] = [
        healthy_fuel_pressure(seed)
        for seed in chunk["random_seed"]
    ]

    # --------------------------------------------------------
    # Healthy sensor-drift metadata
    # --------------------------------------------------------

    chunk["true_sensor_value"] = np.nan
    chunk["measured_sensor_value"] = np.nan

    # --------------------------------------------------------
    # Limit checks
    # --------------------------------------------------------

    coolant = (
        chunk["coolant_temp_C"] > 120.0
    )

    oil_temperature = (
        chunk["oil_temperature_C"] > 130.0
    )

    egt_max = (
        chunk["EGT_max_C"] > 950.0
    )

    egt_split_limit = np.where(
        chunk["fuelflow_kgh"] > 3.0,
        200.0,
        500.0,
    )

    egt_spread = (
        chunk["EGT_spread_C"]
        > egt_split_limit
    )

    fuel_pressure = (
        (chunk["fuel_pressure_bar"] < 2.90)
        |
        (chunk["fuel_pressure_bar"] > 3.10)
    )

    chunk["limit_exceeded"] = (
        coolant
        | oil_temperature
        | egt_max
        | egt_spread
        | fuel_pressure
    ).astype(bool)

    chunk["limit_parameter"] = pd.Series(
        pd.NA,
        index=chunk.index,
        dtype="object",
    )

    chunk["limit_value"] = np.nan

    # First exceeded limit wins.

    mask = coolant

    chunk.loc[
        mask,
        "limit_parameter",
    ] = "coolant_temp_C"

    chunk.loc[
        mask,
        "limit_value",
    ] = 120.0

    mask = (
        (~coolant)
        & oil_temperature
    )

    chunk.loc[
        mask,
        "limit_parameter",
    ] = "oil_temperature_C"

    chunk.loc[
        mask,
        "limit_value",
    ] = 130.0

    mask = (
        (~coolant)
        & (~oil_temperature)
        & egt_max
    )

    chunk.loc[
        mask,
        "limit_parameter",
    ] = "EGT_max_C"

    chunk.loc[
        mask,
        "limit_value",
    ] = 950.0

    mask = (
        (~coolant)
        & (~oil_temperature)
        & (~egt_max)
        & egt_spread
    )

    chunk.loc[
        mask,
        "limit_parameter",
    ] = "EGT_spread_C"

    chunk.loc[
        mask,
        "limit_value",
    ] = egt_split_limit[mask]

    mask = (
        (~coolant)
        & (~oil_temperature)
        & (~egt_max)
        & (~egt_spread)
        & fuel_pressure
    )

    chunk.loc[
        mask,
        "limit_parameter",
    ] = "fuel_pressure_bar"

    chunk.loc[
        mask,
        "limit_value",
    ] = np.where(
        chunk.loc[
            mask,
            "fuel_pressure_bar",
        ] < 2.90,
        2.90,
        3.10,
    )

    return chunk


# ============================================================
# ABNORMAL DATA PREPARATION
# ============================================================

def prepare_abnormal(
    chunk: pd.DataFrame,
) -> pd.DataFrame:

    chunk = chunk.copy()

    if "engine_id" not in chunk.columns:
        fail(
            "Abnormal dataset has no engine_id."
        )

    # --------------------------------------------------------
    # Validate source engine IDs
    # --------------------------------------------------------

    numbers = chunk["engine_id"].map(
        engine_number
    )

    if (
        (numbers < ABNORMAL_ENGINE_MIN)
        |
        (numbers > ABNORMAL_ENGINE_MAX)
    ).any():

        bad = sorted(
            chunk.loc[
                (
                    (numbers < ABNORMAL_ENGINE_MIN)
                    |
                    (numbers > ABNORMAL_ENGINE_MAX)
                ),
                "engine_id",
            ].unique()
        )

        fail(
            "Unexpected abnormal engine IDs:\n"
            + "\n".join(bad)
        )

    # --------------------------------------------------------
    # Remap:
    #
    # ENG_0001 -> ENG_0251
    # ENG_0002 -> ENG_0252
    # ...
    # ENG_0010 -> ENG_0260
    # --------------------------------------------------------

    chunk["engine_id"] = [
        f"ENG_{engine_number(engine_id) + ABNORMAL_TARGET_OFFSET:04d}"
        for engine_id in chunk["engine_id"]
    ]

    return chunk


# ============================================================
# GET CSV HEADER
# ============================================================

def get_header(path: Path) -> list[str]:

    return pd.read_csv(
        path,
        nrows=0,
    ).columns.tolist()


# ============================================================
# VALIDATE SOURCE SCHEMAS
# ============================================================

def validate_source_schemas():

    normal_columns = get_header(
        NORMAL_PATH
    )

    abnormal_columns = get_header(
        ABNORMAL_PATH
    )

    if len(normal_columns) != 55:
        fail(
            f"Expected normal source to have 55 "
            f"columns, found {len(normal_columns)}."
        )

    if len(abnormal_columns) != 68:
        fail(
            f"Expected abnormal source to have 68 "
            f"columns, found {len(abnormal_columns)}."
        )

    normal_set = set(normal_columns)
    abnormal_set = set(abnormal_columns)

    normal_only = normal_set - abnormal_set

    abnormal_only = abnormal_set - normal_set

    if normal_only:
        fail(
            "Unexpected normal-only columns:\n"
            + "\n".join(sorted(normal_only))
        )

    if abnormal_only != set(STAGE7_COLUMNS):
        fail(
            "Abnormal-only columns do not exactly match "
            "Stage-7 columns.\n"
            f"Found: {sorted(abnormal_only)}"
        )

    return normal_columns, abnormal_columns


# ============================================================
# COUNT SOURCE ROWS
# ============================================================

def count_csv_rows(path: Path) -> int:

    total = 0

    with path.open(
        "r",
        encoding="utf-8",
        errors="replace",
        newline="",
    ) as f:

        reader = csv.reader(f)

        # Skip header.
        next(reader, None)

        for _ in reader:
            total += 1

    return total


# ============================================================
# COUNT ENGINES
# ============================================================

def count_engines(
    path: Path,
) -> dict[str, int]:

    counts = {}

    for chunk in pd.read_csv(
        path,
        usecols=["engine_id"],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):

        values = chunk[
            "engine_id"
        ].value_counts()

        for engine_id, count in values.items():

            counts[engine_id] = (
                counts.get(engine_id, 0)
                + int(count)
            )

    return counts


# ============================================================
# WRITE CHUNK
# ============================================================

def write_chunk(
    chunk: pd.DataFrame,
    output_path: Path,
    first_chunk: bool,
) -> int:

    chunk.to_csv(
        output_path,
        mode="w" if first_chunk else "a",
        header=first_chunk,
        index=False,
    )

    return len(chunk)


# ============================================================
# MAIN
# ============================================================

def main():

    section(
        "MASTER DATASET — FINAL PRODUCTION MERGE"
    )

    print(
        f"Project: {PROJECT}"
    )

    print()
    print(
        "Normal:"
    )
    print(
        f"  {NORMAL_PATH}"
    )

    print()
    print(
        "Abnormal:"
    )
    print(
        f"  {ABNORMAL_PATH}"
    )

    print()
    print(
        "Output:"
    )
    print(
        f"  {OUTPUT_PATH}"
    )

    print()
    print(
        f"Chunk size: {CHUNK_SIZE:,}"
    )

    # --------------------------------------------------------
    # FILE CHECK
    # --------------------------------------------------------

    section(
        "1. INPUT FILE CHECK"
    )

    if not NORMAL_PATH.exists():
        fail(
            f"Normal dataset not found:\n"
            f"{NORMAL_PATH}"
        )

    if not ABNORMAL_PATH.exists():
        fail(
            f"Abnormal dataset not found:\n"
            f"{ABNORMAL_PATH}"
        )

    print(
        "Normal dataset   : FOUND"
    )

    print(
        "Abnormal dataset : FOUND"
    )

    # --------------------------------------------------------
    # SOURCE SCHEMA
    # --------------------------------------------------------

    section(
        "2. SOURCE SCHEMA VALIDATION"
    )

    normal_columns, abnormal_columns = (
        validate_source_schemas()
    )

    print(
        "Normal columns   : 55"
    )

    print(
        "Abnormal columns : 68"
    )

    print(
        "Stage-7 columns  : 13"
    )

    print(
        "SOURCE SCHEMA: PASSED"
    )

    # --------------------------------------------------------
    # SOURCE ROW COUNTS
    # --------------------------------------------------------

    section(
        "3. SOURCE ROW COUNT"
    )

    print(
        "Counting normal rows..."
    )

    normal_source_rows = count_csv_rows(
        NORMAL_PATH
    )

    print(
        f"Normal source rows: "
        f"{normal_source_rows:,}"
    )

    print(
        "Counting abnormal rows..."
    )

    abnormal_source_rows = count_csv_rows(
        ABNORMAL_PATH
    )

    print(
        f"Abnormal source rows: "
        f"{abnormal_source_rows:,}"
    )

    expected_total_rows = (
        normal_source_rows
        + abnormal_source_rows
    )

    print()
    print(
        f"EXPECTED MASTER ROWS: "
        f"{expected_total_rows:,}"
    )

    # --------------------------------------------------------
    # ENGINE DISTRIBUTION
    # --------------------------------------------------------

    section(
        "4. SOURCE ENGINE VALIDATION"
    )

    print(
        "Counting normal engines..."
    )

    normal_engines = count_engines(
        NORMAL_PATH
    )

    print(
        f"Normal unique engines: "
        f"{len(normal_engines)}"
    )

    if len(normal_engines) != 250:
        fail(
            f"Expected 250 normal engines, "
            f"found {len(normal_engines)}."
        )

    normal_numbers = sorted(
        engine_number(engine_id)
        for engine_id in normal_engines
    )

    expected_normal_numbers = list(
        range(
            NORMAL_ENGINE_MIN,
            NORMAL_ENGINE_MAX + 1,
        )
    )

    if normal_numbers != expected_normal_numbers:
        fail(
            "Normal engine IDs are not exactly "
            "ENG_0001 through ENG_0250."
        )

    print(
        "Normal engines: ENG_0001 -> ENG_0250"
    )

    print(
        "Normal engine validation: PASSED"
    )

    print()
    print(
        "Counting abnormal engines..."
    )

    abnormal_engines = count_engines(
        ABNORMAL_PATH
    )

    print(
        f"Abnormal unique engines: "
        f"{len(abnormal_engines)}"
    )

    if len(abnormal_engines) != ABNORMAL_ENGINE_MAX:
        fail(
            f"Expected {ABNORMAL_ENGINE_MAX} abnormal engines, "
            f"found {len(abnormal_engines)}."
        )

    abnormal_numbers = sorted(
        engine_number(engine_id)
        for engine_id in abnormal_engines
    )

    expected_abnormal_numbers = list(
        range(
            ABNORMAL_ENGINE_MIN,
            ABNORMAL_ENGINE_MAX + 1,
        )
    )

    if abnormal_numbers != expected_abnormal_numbers:
        fail(
            "Abnormal engine IDs are not exactly "
            f"ENG_0001 through ENG_{ABNORMAL_ENGINE_MAX:04d}."
        )

    print(
        f"Abnormal engines: ENG_0001 -> ENG_{ABNORMAL_ENGINE_MAX:04d}"
    )

    print(
        "Abnormal engine validation: PASSED"
    )

    # --------------------------------------------------------
    # OUTPUT DIRECTORY
    # --------------------------------------------------------

    section(
        "5. OUTPUT PREPARATION"
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if TEMP_PATH.exists():
        print(
            "Removing previous temporary file..."
        )
        TEMP_PATH.unlink()

    if OUTPUT_PATH.exists():
        print()
        print(
            "WARNING: Existing master dataset found."
        )

        print(
            f"Existing file: {OUTPUT_PATH}"
        )

        print()
        print(
            "It will be replaced only after the new "
            "dataset is successfully built."
        )

    print(
        "Output directory: READY"
    )

    # --------------------------------------------------------
    # BUILD NORMAL PART
    # --------------------------------------------------------

    section(
        "6. WRITE NORMAL DATA"
    )

    total_written = 0
    first_chunk = True

    normal_chunk_number = 0

    for chunk in pd.read_csv(
        NORMAL_PATH,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):

        normal_chunk_number += 1

        prepared = prepare_normal(
            chunk
        )

        prepared = prepared.reindex(
            columns=abnormal_columns
        )

        if list(prepared.columns) != list(
            abnormal_columns
        ):
            fail(
                "Normal chunk schema does not match "
                "the canonical 68-column schema."
            )

        written = write_chunk(
            prepared,
            TEMP_PATH,
            first_chunk,
        )

        first_chunk = False
        total_written += written

        print(
            f"Normal chunk "
            f"{normal_chunk_number:>3}: "
            f"+{written:,} rows | "
            f"total={total_written:,}",
            flush=True,
        )

        del chunk
        del prepared

    if total_written != normal_source_rows:
        fail(
            "Normal row count changed during processing.\n"
            f"Source: {normal_source_rows:,}\n"
            f"Written: {total_written:,}"
        )

    print()
    print(
        "NORMAL DATA: COMPLETE"
    )

    # --------------------------------------------------------
    # BUILD ABNORMAL PART
    # --------------------------------------------------------

    section(
        "7. WRITE ABNORMAL DATA"
    )

    abnormal_written = 0
    abnormal_chunk_number = 0

    for chunk in pd.read_csv(
        ABNORMAL_PATH,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):

        abnormal_chunk_number += 1

        prepared = prepare_abnormal(
            chunk
        )

        prepared = prepared.reindex(
            columns=abnormal_columns
        )

        if list(prepared.columns) != list(
            abnormal_columns
        ):
            fail(
                "Abnormal chunk schema changed."
            )

        written = write_chunk(
            prepared,
            TEMP_PATH,
            first_chunk=False,
        )

        abnormal_written += written
        total_written += written

        print(
            f"Abnormal chunk "
            f"{abnormal_chunk_number:>3}: "
            f"+{written:,} rows | "
            f"total={total_written:,}",
            flush=True,
        )

        del chunk
        del prepared

    if abnormal_written != abnormal_source_rows:
        fail(
            "Abnormal row count changed during processing.\n"
            f"Source: {abnormal_source_rows:,}\n"
            f"Written: {abnormal_written:,}"
        )

    print()
    print(
        "ABNORMAL DATA: COMPLETE"
    )

    # --------------------------------------------------------
    # ROW COUNT
    # --------------------------------------------------------

    section(
        "8. ROW COUNT VALIDATION"
    )

    print(
        f"Normal source rows   : "
        f"{normal_source_rows:,}"
    )

    print(
        f"Normal written rows  : "
        f"{total_written - abnormal_written:,}"
    )

    print(
        f"Abnormal source rows : "
        f"{abnormal_source_rows:,}"
    )

    print(
        f"Abnormal written rows: "
        f"{abnormal_written:,}"
    )

    print()
    print(
        f"Expected master rows : "
        f"{expected_total_rows:,}"
    )

    print(
        f"Actual written rows  : "
        f"{total_written:,}"
    )

    if total_written != expected_total_rows:
        fail(
            "MASTER ROW COUNT MISMATCH."
        )

    print(
        "ROW COUNT: PASSED"
    )

    # --------------------------------------------------------
    # REPLACE FINAL FILE
    # --------------------------------------------------------

    section(
        "9. FINALIZE MASTER DATASET"
    )

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    TEMP_PATH.replace(
        OUTPUT_PATH
    )

    print(
        f"Final master dataset:"
    )

    print(
        f"  {OUTPUT_PATH}"
    )

    size_gb = (
        OUTPUT_PATH.stat().st_size
        / (1024 ** 3)
    )

    print(
        f"Size: {size_gb:.2f} GB"
    )

    # --------------------------------------------------------
    # FINAL HEADER
    # --------------------------------------------------------

    section(
        "10. FINAL SCHEMA VALIDATION"
    )

    final_columns = get_header(
        OUTPUT_PATH
    )

    if len(final_columns) != 68:
        fail(
            f"Final master has "
            f"{len(final_columns)} columns; "
            "expected 68."
        )

    if final_columns != abnormal_columns:
        fail(
            "Final master column order does not "
            "match canonical Stage-7 schema."
        )

    print(
        "Columns: 68"
    )

    print(
        "Column order: PASSED"
    )

    # --------------------------------------------------------
    # FINAL ENGINE CHECK
    # --------------------------------------------------------

    section(
        "11. FINAL ENGINE ID VALIDATION"
    )

    final_engines = count_engines(
        OUTPUT_PATH
    )

    final_engine_numbers = sorted(
        engine_number(engine_id)
        for engine_id in final_engines
    )

    expected_final_numbers = list(
        range(1, ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX + 1)
    )

    if final_engine_numbers != (
        expected_final_numbers
    ):
        fail(
            "Final engine IDs are not exactly "
            f"ENG_0001 through ENG_{ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX:04d}."
        )

    print(
        "Healthy engines : ENG_0001 -> ENG_0250"
    )

    print(
        f"Abnormal engines: ENG_{ABNORMAL_TARGET_OFFSET + 1:04d} -> "
        f"ENG_{ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX:04d}"
    )

    print(
        f"Unique engines  : {ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX}"
    )

    print(
        "ENGINE IDs: PASSED"
    )

    # --------------------------------------------------------
    # FINAL LABEL CHECK
    # --------------------------------------------------------

    section(
        "12. FINAL LABEL VALIDATION"
    )

    fault_counts = {}

    severity_counts = {}

    for chunk in pd.read_csv(
        OUTPUT_PATH,
        usecols=[
            "fault_present",
            "fault_type",
            "fault_severity",
        ],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):

        for value, count in (
            chunk["fault_type"]
            .value_counts(dropna=False)
            .items()
        ):

            fault_counts[value] = (
                fault_counts.get(value, 0)
                + int(count)
            )

        for value, count in (
            chunk["fault_severity"]
            .value_counts(dropna=False)
            .items()
        ):

            severity_counts[value] = (
                severity_counts.get(value, 0)
                + int(count)
            )

        if not chunk[
            "fault_present"
        ].isin([True, False]).all():

            fail(
                "Invalid fault_present value."
            )

    print(
        "Fault types:"
    )

    for fault, count in sorted(
        fault_counts.items(),
        key=lambda x: str(x[0]),
    ):
        print(
            f"  {fault}: {count:,}"
        )

    print()
    print(
        "Severities:"
    )

    for severity, count in sorted(
        severity_counts.items(),
        key=lambda x: str(x[0]),
    ):
        print(
            f"  {severity}: {count:,}"
        )

    if "healthy" not in fault_counts:
        fail(
            "Healthy class missing."
        )

    missing_faults = (
        EXPECTED_FAULT_TYPES
        - set(fault_counts)
    )

    if missing_faults:
        fail(
            "Expected fault types missing:\n"
            + "\n".join(sorted(missing_faults))
        )

    print()
    print(
        "LABEL VALIDATION: PASSED"
    )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    section(
        "MASTER DATASET BUILD: PASSED"
    )

    print(
        f"Rows    : {total_written:,}"
    )

    print(
        "Columns : 68"
    )

    print(
        f"Engines : {ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX}"
    )

    print(
        "Normal  : ENG_0001 -> ENG_0250"
    )

    print(
        f"Abnormal: ENG_{ABNORMAL_TARGET_OFFSET + 1:04d} -> "
        f"ENG_{ABNORMAL_TARGET_OFFSET + ABNORMAL_ENGINE_MAX:04d}"
    )

    print()
    print(
        "NO DEDUPLICATION PERFORMED"
    )

    print(
        "NO SOURCE DATA MODIFIED"
    )

    print()
    print(
        "MASTER DATASET READY FOR ML PIPELINE"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print(
            "BUILD INTERRUPTED BY USER."
        )
        sys.exit(1)
    except Exception as exc:
        print()
        print(
            str(exc)
        )
        sys.exit(1)