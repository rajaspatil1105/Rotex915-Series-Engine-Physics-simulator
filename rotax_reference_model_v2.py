"""
rotax_reference_model.py

Queryable reference model for the OFFICIAL Rotax 915 iS performance-map CSV.

Purpose
-------
This module is NOT the ML training dataset and MUST NOT be imported by the
Cantera engine model. It is used only for:
1. validation of simulator outputs against the official engine deck; and
2. selecting/constructing Phase-1 operating conditions.

Design rules
------------
- The original CSV is treated as read-only.
- No silent extrapolation is allowed in validation mode.
- Boundary mode may return a nearest-neighbour value only when explicitly
  requested, and marks the result as extrapolated.
- Temperature-offset structure is verified from the data; it is never inferred
  from "minimum temperature at altitude".
- Altitude/ambient-pressure consistency is checked against a standard
  atmosphere relation as a diagnostic only.
- Leave-one-out interpolation checks estimate interpolation error independently
  of the Cantera model.
- Provenance is stored in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import Delaunay, QhullError


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

PROVENANCE = {
    "engine": "ROTAX 915 iS series",
    "source_type": "Official manufacturer engine-deck/performance data",
    "source_document": "ROTAX 915 iS series official documentation",
    "source_revision": "REPLACE_WITH_EXACT_DOCUMENT_REVISION",
    "source_pages_or_appendix": "REPLACE_WITH_EXACT_PAGE_OR_APPENDIX",
    "source_url": "REPLACE_WITH_OFFICIAL_DOWNLOAD_URL",
    "date_obtained": "REPLACE_WITH_DATE_OBTAINED",
    "notes": (
        "CSV supplied by the project team from official Rotax manufacturer "
        "documentation. Preserve the original file unchanged."
    ),
}


# ---------------------------------------------------------------------------
# CSV schema
# ---------------------------------------------------------------------------

COL_RPM = "rpm"
COL_THROTTLE = "throttle_pct"
COL_ALT = "alt_ft"
COL_PAMB = "p_amb_bar"
COL_TAMB = "t_amb_C"

OUTPUT_COLUMNS = [
    "power_kW",
    "fuelflow_kgh",
    "p_plenum_bar",
    "t_plenum_K",
]

# The project currently expects these temperature offsets, but the module
# verifies them rather than assuming them.
EXPECTED_TEMP_BANDS_C = (0.0, 15.0, 30.0, 45.0)

# Tolerances should be deliberately visible/configurable.
TEMP_BAND_TOL_C = 3.0
PRESSURE_CHECK_TOL_BAR = 0.02

# Standard atmosphere diagnostic constants.
ISA_SEA_LEVEL_C = 15.0
ISA_LAPSE_C_PER_FT = 1.98 / 1000.0
P0_BAR = 1.01325
G0 = 9.80665
R_AIR = 287.052
T0_K = 288.15
LAPSE_K_PER_M = 0.0065


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceQueryResult:
    power_kW: float
    fuelflow_kgh: float
    p_plenum_bar: float
    t_plenum_K: float
    mode: str
    exact: bool
    interpolated: bool
    extrapolated: bool


@dataclass(frozen=True)
class MetricResult:
    parameter: str
    n: int
    mae: float
    rmse: float
    mape_percent: float


# ---------------------------------------------------------------------------
# Atmosphere helpers
# ---------------------------------------------------------------------------

def isa_temp_c(alt_ft: float) -> float:
    """Approximate ISA temperature in degC below the tropopause."""
    return ISA_SEA_LEVEL_C - ISA_LAPSE_C_PER_FT * float(alt_ft)


def isa_pressure_bar(alt_ft: float) -> float:
    """
    Approximate standard-atmosphere pressure in bar below 11 km.

    This is a diagnostic consistency check, NOT a replacement for the
    manufacturer's pressure values.
    """
    h_m = max(0.0, float(alt_ft)) * 0.3048
    if h_m > 11000:
        raise ValueError("isa_pressure_bar currently supports altitudes <= 11 km.")

    T = T0_K - LAPSE_K_PER_M * h_m
    exponent = G0 / (R_AIR * LAPSE_K_PER_M)
    return P0_BAR * (T / T0_K) ** exponent


def _nearest_band(raw_offset: float,
                  bands: Iterable[float] = EXPECTED_TEMP_BANDS_C,
                  tol: float = TEMP_BAND_TOL_C) -> float:
    bands = tuple(float(x) for x in bands)
    nearest = min(bands, key=lambda b: abs(b - raw_offset))
    if abs(nearest - raw_offset) > tol:
        raise ValueError(
            f"Temperature offset {raw_offset:.3f} C does not match any "
            f"expected band {bands} within ±{tol} C."
        )
    return nearest


# ---------------------------------------------------------------------------
# Main reference model
# ---------------------------------------------------------------------------

class RotaxReferenceModel:
    """
    Read-only wrapper around the official Rotax 915 iS engine deck.

    Query modes:
      - validation: must be inside the real-data convex hull; otherwise raises.
      - boundary: permits nearest-neighbour fallback outside the hull, but
                  marks the result as extrapolated.
    """

    def __init__(
        self,
        csv_path: str | Path,
        *,
        verify_temperature_bands: bool = True,
        verify_pressure_altitude: bool = True,
    ):
        self.csv_path = Path(csv_path)
        self.df = pd.read_csv(self.csv_path)

        self._validate_columns()
        self._validate_numeric_columns()

        if verify_temperature_bands:
            self._verify_temperature_structure()

        self._compute_temp_offset()

        if verify_pressure_altitude:
            self.pressure_altitude_report = self._pressure_altitude_check()

        self._build_interpolators()

    # ------------------------- validation of source -----------------------

    def _validate_columns(self) -> None:
        required = {
            COL_RPM,
            COL_THROTTLE,
            COL_ALT,
            COL_PAMB,
            COL_TAMB,
            *OUTPUT_COLUMNS,
        }
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    def _validate_numeric_columns(self) -> None:
        numeric = [
            COL_RPM, COL_THROTTLE, COL_ALT, COL_PAMB, COL_TAMB, *OUTPUT_COLUMNS
        ]
        for col in numeric:
            self.df[col] = pd.to_numeric(self.df[col], errors="raise")

        if self.df[numeric].isna().any().any():
            raise ValueError("CSV contains NaN values in required numeric columns.")

    def _verify_temperature_structure(self) -> None:
        """
        Verify that each altitude has a genuine baseline and the expected
        offset bands. This intentionally does NOT use the minimum temperature
        as a guessed baseline.

        This verification is strict: a single unambiguous baseline must be
        present for each altitude where all EXPECTED_TEMP_BANDS_C are
        represented within tolerance. Any missing or ambiguous baselines
        raise a ValueError.
        """
        failures = []

        for alt, group in self.df.groupby(COL_ALT):
            temps = np.sort(group[COL_TAMB].unique())

            # Find candidate baselines such that all expected offsets are
            # represented within tolerance.
            candidates = []
            for baseline in temps:
                offsets = temps - baseline
                ok = all(
                    np.any(np.isclose(offsets, band, atol=TEMP_BAND_TOL_C))
                    for band in EXPECTED_TEMP_BANDS_C
                )
                if ok:
                    candidates.append(float(baseline))

            if not candidates:
                failures.append(
                    f"alt_ft={alt}: no baseline supports all expected bands "
                    f"{EXPECTED_TEMP_BANDS_C}; temperatures={temps.tolist()}"
                )
                continue

            # Ambiguity: more than one candidate baseline is not allowed.
            if len(candidates) > 1:
                failures.append(
                    f"alt_ft={alt}: ambiguous baselines {candidates}; "
                    f"temperatures={temps.tolist()}"
                )
                continue

            baseline = candidates[0]
            offsets = temps - baseline
            matched = [_nearest_band(x) for x in offsets]

            # Confirm each expected band is actually present.
            missing = [
                band for band in EXPECTED_TEMP_BANDS_C
                if band not in matched
            ]
            if missing:
                failures.append(
                    f"alt_ft={alt}: missing bands {missing}; "
                    f"temps={temps.tolist()}"
                )

        if failures:
            msg = "Temperature-band verification failed:\n- " + "\n- ".join(failures)
            raise ValueError(msg)

    def _compute_temp_offset(self) -> None:
        """
        Recover the verified temperature-offset band from the source data.

        This method is strict: for each altitude there must be exactly one
        unambiguous baseline that supports all EXPECTED_TEMP_BANDS_C within
        tolerance. If such a baseline cannot be determined for any altitude,
        raise ValueError. This ensures the module never fabricates or silently
        infers missing temperature bands.
        """
        baselines = {}

        for alt, group in self.df.groupby(COL_ALT):
            temps = np.sort(group[COL_TAMB].unique())
            candidates = []
            for baseline in temps:
                offsets = temps - baseline
                if all(
                    np.any(np.isclose(offsets, band, atol=TEMP_BAND_TOL_C))
                    for band in EXPECTED_TEMP_BANDS_C
                ):
                    candidates.append(float(baseline))

            if not candidates:
                raise ValueError(
                    f"Cannot determine verified temperature baseline at {alt} ft; "
                    "expected bands not present."
                )

            # Require an unambiguous single baseline per altitude.
            if len(candidates) != 1:
                raise ValueError(
                    f"Ambiguous temperature baseline candidates at {alt} ft: "
                    f"{candidates}. Cannot proceed without unambiguous bands."
                )

            baselines[alt] = candidates[0]

        baseline_series = self.df[COL_ALT].map(baselines)
        raw_offset = self.df[COL_TAMB] - baseline_series
        # Use strict nearest-band mapping which raises if an offset does not
        # match any expected band within tolerance.
        self.df["temp_offset_band"] = raw_offset.map(_nearest_band)

    def _pressure_altitude_check(self) -> pd.DataFrame:
        """Return a diagnostic table comparing source pressure with ISA."""
        out = self.df[[COL_ALT, COL_PAMB]].drop_duplicates().copy()
        out["isa_pressure_bar"] = out[COL_ALT].map(isa_pressure_bar)
        out["pressure_error_bar"] = out[COL_PAMB] - out["isa_pressure_bar"]
        out["pressure_error_percent"] = (
            100.0 * out["pressure_error_bar"] / out["isa_pressure_bar"]
        )
        out["within_tolerance"] = (
            out["pressure_error_bar"].abs() <= PRESSURE_CHECK_TOL_BAR
        )
        return out.sort_values(COL_ALT).reset_index(drop=True)

    # ----------------------------- interpolator ---------------------------

    def _build_interpolators(self) -> None:
        # Compute axis ranges dynamically (including temperature offset bands
        # derived from the data) so normalization reflects the actual dataset.
        self._axis_ranges = {
            COL_RPM: (float(self.df[COL_RPM].min()), float(self.df[COL_RPM].max())),
            COL_THROTTLE: (
                float(self.df[COL_THROTTLE].min()),
                float(self.df[COL_THROTTLE].max()),
            ),
            COL_ALT: (float(self.df[COL_ALT].min()), float(self.df[COL_ALT].max())),
            "temp_offset_band": (
                float(self.df["temp_offset_band"].min()),
                float(self.df["temp_offset_band"].max()),
            ),
        }

        # Detect duplicate 4-D operating coordinates and ensure they do not
        # conflict. If duplicates are present and have identical outputs they
        # are deduplicated (kept first). If duplicates disagree, raise an
        # error listing the conflicting rows.
        coords = [COL_RPM, COL_THROTTLE, COL_ALT, "temp_offset_band"]
        dup_groups = self.df[self.df.duplicated(subset=coords, keep=False)].copy()
        if not dup_groups.empty:
            # Group and check consistency
            conflicts = []
            for key, group in dup_groups.groupby(coords):
                outputs = group[OUTPUT_COLUMNS]
                # Check if all output rows are equal (within numeric tolerance)
                first = outputs.iloc[0]
                # Use np.allclose for floats; treat NaNs as unequal
                equal = all(
                    np.allclose(outputs[col].to_numpy(), first[col])
                    for col in OUTPUT_COLUMNS
                )
                if not equal:
                    conflicts.append((key, group.index.tolist(), group[OUTPUT_COLUMNS].to_dict(orient='list')))
            if conflicts:
                msgs = []
                for key, idxs, vals in conflicts:
                    msgs.append(
                        f"coords={key} conflicting rows indexes={idxs} values={vals}"
                    )
                raise ValueError("Conflicting duplicate operating points detected:\n- " + "\n- ".join(msgs))
            # No conflicts: drop duplicate rows keeping the first occurrence
            self._df_model = self.df.drop_duplicates(subset=coords, keep='first').reset_index(drop=True)
        else:
            self._df_model = self.df.copy()

        points_norm = self._normalize_points(
            self._df_model[COL_RPM].to_numpy(),
            self._df_model[COL_THROTTLE].to_numpy(),
            self._df_model[COL_ALT].to_numpy(),
            self._df_model["temp_offset_band"].to_numpy(),
        )

        try:
            self._hull = Delaunay(points_norm)
        except QhullError as exc:
            unique_pts = np.unique(points_norm, axis=0).shape[0]
            raise ValueError(
                "Could not construct a 4-D convex hull from the reference data. "
                f"Unique operating points after aggregation: {unique_pts}. "
                "Check for duplicate or degenerate points."
            ) from exc

        self._linear_interp = {
            col: LinearNDInterpolator(points_norm, self._df_model[col].to_numpy())
            for col in OUTPUT_COLUMNS
        }
        self._nearest_interp = {
            col: NearestNDInterpolator(points_norm, self._df_model[col].to_numpy())
            for col in OUTPUT_COLUMNS
        }

    def _normalize_points(self, rpm, throttle, alt, temp_offset):
        def norm(vals, key):
            lo, hi = self._axis_ranges[key]
            if hi == lo:
                raise ValueError(f"Axis {key} has zero range.")
            return (np.asarray(vals, dtype=float) - lo) / (hi - lo)

        return np.column_stack([
            norm(rpm, COL_RPM),
            norm(throttle, COL_THROTTLE),
            norm(alt, COL_ALT),
            norm(temp_offset, "temp_offset_band"),
        ])

    # ------------------------------- query --------------------------------

    def _point_norm(
        self,
        rpm: float,
        throttle_pct: float,
        alt_ft: float,
        temp_offset_band: float,
    ) -> np.ndarray:
        if temp_offset_band not in EXPECTED_TEMP_BANDS_C:
            raise ValueError(
                f"temp_offset_band must be one of {EXPECTED_TEMP_BANDS_C}; "
                f"got {temp_offset_band}"
            )

        return self._normalize_points(
            [rpm], [throttle_pct], [alt_ft], [temp_offset_band]
        )

    def _inside_axis_bounds(
        self, rpm: float, throttle_pct: float, alt_ft: float
    ) -> bool:
        return (
            self._axis_ranges[COL_RPM][0] <= rpm <= self._axis_ranges[COL_RPM][1]
            and self._axis_ranges[COL_THROTTLE][0]
            <= throttle_pct
            <= self._axis_ranges[COL_THROTTLE][1]
            and self._axis_ranges[COL_ALT][0] <= alt_ft <= self._axis_ranges[COL_ALT][1]
        )

    def query(
        self,
        rpm: float,
        throttle_pct: float,
        alt_ft: float,
        temp_offset_band: float = 0.0,
        *,
        mode: Literal["validation", "boundary"] = "validation",
    ) -> ReferenceQueryResult:
        """
        Query the reference model.

        validation:
            Hard-fails if the point is outside the source data's convex hull.

        boundary:
            Uses linear interpolation when possible. If outside the hull,
            explicitly uses nearest-neighbour and marks extrapolated=True.
            This mode is for exploratory/boundary-condition work only.
        """
        if mode not in {"validation", "boundary"}:
            raise ValueError("mode must be 'validation' or 'boundary'")

        # Check for an exact source row first.
        exact_rows = self.find_exact_rows(
            rpm=rpm,
            throttle_pct=throttle_pct,
            alt_ft=alt_ft,
            temp_offset_band=temp_offset_band,
        )
        if len(exact_rows) > 0:
            row = exact_rows.iloc[0]
            return ReferenceQueryResult(
                power_kW=float(row["power_kW"]),
                fuelflow_kgh=float(row["fuelflow_kgh"]),
                p_plenum_bar=float(row["p_plenum_bar"]),
                t_plenum_K=float(row["t_plenum_K"]),
                mode=mode,
                exact=True,
                interpolated=False,
                extrapolated=False,
            )

        point_norm = self._point_norm(
            rpm, throttle_pct, alt_ft, temp_offset_band
        )
        in_axis_bounds = self._inside_axis_bounds(rpm, throttle_pct, alt_ft)
        in_hull = bool(self._hull.find_simplex(point_norm)[0] >= 0)

        if mode == "validation" and (not in_axis_bounds or not in_hull):
            raise ValueError(
                "Validation query is outside the real reference-data region. "
                "No extrapolation is permitted. "
                f"conditions=(rpm={rpm}, throttle={throttle_pct}, "
                f"alt_ft={alt_ft}, temp_offset={temp_offset_band})"
            )

        values = {}
        interpolated = False
        extrapolated = False

        for col in OUTPUT_COLUMNS:
            # Call linear interpolator safely and extract a scalar when present.
            res = self._linear_interp[col](point_norm)
            try:
                arr = np.asarray(res).ravel()
                value = float(arr[0]) if arr.size > 0 else float("nan")
            except Exception:
                value = float("nan")

            if np.isfinite(value):
                values[col] = float(value)
                interpolated = True
            else:
                if mode == "validation":
                    raise ValueError(
                        f"Linear interpolation failed for {col}; "
                        "validation mode refuses extrapolation."
                    )

                # Fallback to nearest-neighbour with safe extraction.
                res_nn = self._nearest_interp[col](point_norm)
                try:
                    values[col] = float(np.asarray(res_nn).ravel()[0])
                except Exception:
                    raise ValueError(f"Nearest-neighbour interpolation failed for {col}.")
                extrapolated = True

        return ReferenceQueryResult(
            power_kW=values["power_kW"],
            fuelflow_kgh=values["fuelflow_kgh"],
            p_plenum_bar=values["p_plenum_bar"],
            t_plenum_K=values["t_plenum_K"],
            mode=mode,
            exact=False,
            interpolated=interpolated,
            extrapolated=extrapolated,
        )

    # --------------------------- exact-row check --------------------------

    def find_exact_rows(
        self,
        *,
        rpm: float,
        throttle_pct: float,
        alt_ft: float,
        temp_offset_band: float = 0.0,
    ) -> pd.DataFrame:
        """Return source rows matching an operating point."""
        mask = (
            np.isclose(self.df[COL_RPM], rpm)
            & np.isclose(self.df[COL_THROTTLE], throttle_pct)
            & np.isclose(self.df[COL_ALT], alt_ft)
            & np.isclose(self.df["temp_offset_band"], temp_offset_band)
        )
        return self.df.loc[mask].copy()

    # --------------------------- coverage report --------------------------

    def coverage_report(self) -> str:
        lines = ["ROTAX 915 iS reference-data coverage"]
        lines.append(f"  File: {self.csv_path}")
        lines.append(f"  Rows: {len(self.df)}")
        lines.append(f"  RPM: {sorted(self.df[COL_RPM].unique().tolist())}")
        lines.append(
            f"  Throttle %: {sorted(self.df[COL_THROTTLE].unique().tolist())}"
        )
        lines.append(
            f"  Altitude ft: {sorted(self.df[COL_ALT].unique().tolist())}"
        )
        lines.append(
            "  Temperature offset bands C: "
            f"{sorted(self.df['temp_offset_band'].unique().tolist())}"
        )
        lines.append(
            f"  Ambient pressure bar: "
            f"{self.df[COL_PAMB].min():.5f} to {self.df[COL_PAMB].max():.5f}"
        )
        lines.append(
            f"  Ambient temperature C: "
            f"{self.df[COL_TAMB].min():.2f} to {self.df[COL_TAMB].max():.2f}"
        )

        full_grid = (
            self.df[COL_RPM].nunique()
            * self.df[COL_THROTTLE].nunique()
            * self.df[COL_ALT].nunique()
            * self.df["temp_offset_band"].nunique()
        )
        missing = full_grid - len(self.df)
        lines.append(
            f"  Full Cartesian grid size: {full_grid}; "
            f"observed rows: {len(self.df)}; "
            f"absent combinations: {missing}"
        )
        lines.append(
            "  IMPORTANT: absent combinations are not filled automatically."
        )
        return "\n".join(lines)

    # ------------------------ interpolation CV ----------------------------

    def leave_one_out_check(
        self,
        *,
        max_points: int | None = None,
        random_state: int = 42,
    ) -> pd.DataFrame:
        """
        Leave-one-out interpolation diagnostic.

        This estimates interpolation error independently of Cantera.

        For speed, max_points can be set to a deterministic random subset.
        A point is evaluated only if the remaining points contain it inside
        their convex hull. Otherwise it is reported as skipped.
        """
        rng = np.random.default_rng(random_state)
        indices = np.arange(len(self.df))

        if max_points is not None and max_points < len(indices):
            indices = rng.choice(indices, size=max_points, replace=False)
            indices = np.sort(indices)

        rows = []

        for idx in indices:
            train_mask = np.ones(len(self.df), dtype=bool)
            train_mask[idx] = False

            train_points = self._normalize_points(
                self.df.loc[train_mask, COL_RPM].to_numpy(),
                self.df.loc[train_mask, COL_THROTTLE].to_numpy(),
                self.df.loc[train_mask, COL_ALT].to_numpy(),
                self.df.loc[train_mask, "temp_offset_band"].to_numpy(),
            )

            test_point = self._normalize_points(
                [self.df.loc[idx, COL_RPM]],
                [self.df.loc[idx, COL_THROTTLE]],
                [self.df.loc[idx, COL_ALT]],
                [self.df.loc[idx, "temp_offset_band"]],
            )

            try:
                hull = Delaunay(train_points)
                inside = bool(hull.find_simplex(test_point)[0] >= 0)
            except QhullError:
                inside = False

            if not inside:
                rows.append({
                    "row_index": idx,
                    "status": "skipped_outside_leave_one_out_hull",
                })
                continue

            predictions = {}
            for col in OUTPUT_COLUMNS:
                interp = LinearNDInterpolator(
                    train_points, self.df.loc[train_mask, col].to_numpy()
                )
                predictions[col] = float(interp(test_point)[0])

            result = {"row_index": idx, "status": "evaluated"}
            for col in OUTPUT_COLUMNS:
                actual = float(self.df.loc[idx, col])
                pred = predictions[col]
                result[f"{col}_actual"] = actual
                result[f"{col}_predicted"] = pred
                result[f"{col}_abs_error"] = abs(pred - actual)
                result[f"{col}_percent_error"] = (
                    100.0 * abs(pred - actual) / abs(actual)
                    if actual != 0 else np.nan
                )
            rows.append(result)

        return pd.DataFrame(rows)

    # ----------------------------- metadata -------------------------------

    def save_metadata(self, output_path: str | Path) -> None:
        import json

        payload = {
            "provenance": PROVENANCE,
            "coverage": {
                "rows": len(self.df),
                "rpm_values": sorted(self.df[COL_RPM].unique().tolist()),
                "throttle_values": sorted(
                    self.df[COL_THROTTLE].unique().tolist()
                ),
                "altitude_values_ft": sorted(
                    self.df[COL_ALT].unique().tolist()
                ),
                "temperature_offset_bands_C": sorted(
                    self.df["temp_offset_band"].unique().tolist()
                ),
            },
            "interpolation": {
                "method": "LinearNDInterpolator",
                "fallback": "NearestNDInterpolator",
                "fallback_allowed_only_in": "boundary mode",
                "validation_extrapolation": "forbidden",
            },
        }

        Path(output_path).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Validation metrics
# ---------------------------------------------------------------------------

def calculate_metrics(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
    *,
    parameter: str,
) -> MetricResult:
    """Calculate MAE, RMSE and MAPE for one parameter."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    if actual.shape != predicted.shape:
        raise ValueError("actual and predicted must have the same shape.")

    error = predicted - actual
    nonzero = actual != 0

    mape = (
        float(np.mean(np.abs(error[nonzero] / actual[nonzero])) * 100)
        if np.any(nonzero)
        else float("nan")
    )

    return MetricResult(
        parameter=parameter,
        n=len(actual),
        mae=float(np.mean(np.abs(error))),
        rmse=float(np.sqrt(np.mean(error ** 2))),
        mape_percent=mape,
    )


def validation_metrics(
    reference_df: pd.DataFrame,
    simulated_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compare simulator output against reference values.

    Both DataFrames must be aligned row-for-row and contain OUTPUT_COLUMNS.
    """
    if len(reference_df) != len(simulated_df):
        raise ValueError("Reference and simulated DataFrames have different lengths.")

    results = []
    for col in OUTPUT_COLUMNS:
        metric = calculate_metrics(
            reference_df[col],
            simulated_df[col],
            parameter=col,
        )
        results.append(metric.__dict__)

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rotax 915 iS reference model")
    parser.add_argument("csv", help="Path to the official Rotax CSV")
    parser.add_argument(
        "--metadata",
        default=None,
        help="Optional path for metadata JSON",
    )
    parser.add_argument(
        "--loo",
        action="store_true",
        help="Run leave-one-out interpolation diagnostic",
    )
    parser.add_argument(
        "--loo-max-points",
        type=int,
        default=250,
        help="Maximum LOO points; default 250",
    )
    args = parser.parse_args()

    ref = RotaxReferenceModel(args.csv)

    print(ref.coverage_report())
    print("\nPressure/altitude diagnostic:")
    print(ref.pressure_altitude_report.to_string(index=False))

    # Exact point: must be inside the real data hull.
    exact = ref.query(
        rpm=5800,
        throttle_pct=100.0,
        alt_ft=0,
        temp_offset_band=0.0,
        mode="validation",
    )
    print("\nExact/reference point:")
    print(exact)

    # Interior point: interpolation is allowed.
    interior = ref.query(
        rpm=5200,
        throttle_pct=80.0,
        alt_ft=10000,
        temp_offset_band=15.0,
        mode="validation",
    )
    print("\nInterior interpolated point:")
    print(interior)

    # Boundary mode example: if outside the hull, nearest-neighbour is explicit.
    boundary = ref.query(
        rpm=3000,
        throttle_pct=100.0,
        alt_ft=22000,
        temp_offset_band=45.0,
        mode="boundary",
    )
    print("\nBoundary-mode query:")
    print(boundary)

    if args.metadata:
        ref.save_metadata(args.metadata)
        print(f"\nMetadata written to: {args.metadata}")

    if args.loo:
        loo = ref.leave_one_out_check(max_points=args.loo_max_points)
        print("\nLeave-one-out summary:")
        evaluated = loo[loo["status"] == "evaluated"]
        print(f"Evaluated: {len(evaluated)}")
        print(f"Skipped:   {len(loo) - len(evaluated)}")

        for col in OUTPUT_COLUMNS:
            err_col = f"{col}_percent_error"
            if err_col in evaluated:
                print(
                    f"{col}: "
                    f"mean={evaluated[err_col].mean():.3f}% | "
                    f"median={evaluated[err_col].median():.3f}% | "
                    f"max={evaluated[err_col].max():.3f}%"
                )
