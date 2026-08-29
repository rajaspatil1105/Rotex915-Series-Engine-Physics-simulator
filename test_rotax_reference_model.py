import os
import pandas as pd
import numpy as np
import pytest

from rotax_reference_model_v2 import (
    RotaxReferenceModel,
    COL_RPM,
    COL_THROTTLE,
    COL_ALT,
    COL_PAMB,
    COL_TAMB,
    OUTPUT_COLUMNS,
    EXPECTED_TEMP_BANDS_C,
)


def make_dataframe(rpms, throttles, alts, baseline_by_alt):
    rows = []
    for alt in alts:
        baseline = baseline_by_alt[alt]
        for rpm in rpms:
            for thr in throttles:
                for offset in EXPECTED_TEMP_BANDS_C:
                    tamb = baseline + offset
                    pamb = 1.0  # simple placeholder
                    # simple deterministic outputs
                    power = rpm * 0.001 + thr * 0.01 + alt * 0.0001 + offset * 0.1
                    fuelflow = power * 0.2
                    p_plenum = 1.0 + offset * 0.001
                    t_plenum = 300.0 + offset
                    rows.append({
                        COL_RPM: rpm,
                        COL_THROTTLE: thr,
                        COL_ALT: alt,
                        COL_PAMB: pamb,
                        COL_TAMB: tamb,
                        "power_kW": power,
                        "fuelflow_kgh": fuelflow,
                        "p_plenum_bar": p_plenum,
                        "t_plenum_K": t_plenum,
                    })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_csv(tmp_path):
    rpms = [4000, 5800]
    thr = [50.0, 100.0]
    alts = [0, 10000]
    baselines = {0: 10.0, 10000: 5.0}
    df = make_dataframe(rpms, thr, alts, baselines)
    p = tmp_path / "rotax_sample.csv"
    df.to_csv(p, index=False)
    return p


def test_valid_temperature_bands(sample_csv):
    # Should initialize fine with verification enabled
    model = RotaxReferenceModel(sample_csv)
    assert hasattr(model, "df")
    assert "temp_offset_band" in model.df.columns


def test_invalid_temperature_bands(tmp_path):
    # Missing one expected band -> should raise during init
    df = make_dataframe([4000], [100.0], [0], {0: 10.0})
    # drop one band (e.g., remove offset 45)
    df = df[~np.isclose(df[COL_TAMB], 10.0 + EXPECTED_TEMP_BANDS_C[-1])]
    p = tmp_path / "bad_temp.csv"
    df.to_csv(p, index=False)
    with pytest.raises(ValueError):
        RotaxReferenceModel(p)


def test_exact_point_detection(sample_csv):
    model = RotaxReferenceModel(sample_csv)
    # pick a row from source
    row = model.df.iloc[0]
    res = model.query(rpm=float(row[COL_RPM]), throttle_pct=float(row[COL_THROTTLE]), alt_ft=float(row[COL_ALT]), temp_offset_band=float(row["temp_offset_band"]), mode="validation")
    assert res.exact is True
    assert res.interpolated is False


def test_interpolated_point(sample_csv):
    model = RotaxReferenceModel(sample_csv)
    # choose interior point (average of bounds)
    rpm = (model.df[COL_RPM].min() + model.df[COL_RPM].max()) / 2.0
    thr = (model.df[COL_THROTTLE].min() + model.df[COL_THROTTLE].max()) / 2.0
    alt = (model.df[COL_ALT].min() + model.df[COL_ALT].max()) / 2.0
    band = list(model.df["temp_offset_band"].unique())[0]
    res = model.query(rpm=rpm, throttle_pct=thr, alt_ft=alt, temp_offset_band=band, mode="validation")
    assert res.exact is False
    assert res.interpolated is True


def test_validation_outside_hull(sample_csv):
    model = RotaxReferenceModel(sample_csv)
    with pytest.raises(ValueError):
        model.query(rpm=1000, throttle_pct=0.0, alt_ft=50000, temp_offset_band=0.0, mode="validation")


def test_boundary_extrapolation(sample_csv):
    model = RotaxReferenceModel(sample_csv)
    res = model.query(rpm=1000, throttle_pct=0.0, alt_ft=50000, temp_offset_band=0.0, mode="boundary")
    assert res.extrapolated is True


def test_identical_duplicate_rows(tmp_path):
    # Create duplicate identical rows
    rpms = [4000, 5800]
    thr = [50.0, 100.0]
    alts = [0, 10000]
    baselines = {0: 10.0, 10000: 5.0}
    df = make_dataframe(rpms, thr, alts, baselines)
    # duplicate one row exactly
    df2 = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    p = tmp_path / "dup_same.csv"
    df2.to_csv(p, index=False)
    # Should initialize without error (duplicates identical)
    model = RotaxReferenceModel(p)
    # ensure duplicates removed in internal model
    coords = [COL_RPM, COL_THROTTLE, COL_ALT, "temp_offset_band"]
    assert not model._df_model.duplicated(subset=coords).any()


def test_conflicting_duplicate_rows(tmp_path):
    rpms = [4000]
    thr = [100.0]
    alts = [0]
    baselines = {0: 10.0}
    df = make_dataframe(rpms, thr, alts, baselines)
    # create a conflicting duplicate by changing an output in duplicate
    dup = df.iloc[[0]].copy()
    dup.loc[:, "power_kW"] = dup.loc[:, "power_kW"] + 1.0
    df2 = pd.concat([df, dup], ignore_index=True)
    p = tmp_path / "dup_conflict.csv"
    df2.to_csv(p, index=False)
    with pytest.raises(ValueError):
        RotaxReferenceModel(p)


def test_pressure_altitude_consistency(sample_csv):
    model = RotaxReferenceModel(sample_csv)
    report = model.pressure_altitude_report
    assert "isa_pressure_bar" in report.columns
    assert "within_tolerance" in report.columns
