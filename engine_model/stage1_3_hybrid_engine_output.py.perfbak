"""
Stage 1.3 hybrid engine-output layer.

Production rule:
- The Rotax performance-map CSV is the authoritative source for absolute
  engine outputs.
- Cantera is retained only as a supporting physics layer for features and
  relative/differential behavior.

This module does not modify the CSV, calibration files, or the Stage 1.2
validated architecture. It provides:
- strict CSV-backed engine-output lookup/interpolation
- explicit provenance on calibrated outputs
- a separate container for Cantera-derived supporting features

The unresolved fired Cantera cycle remains experimental and is not used as a
production authority for power or torque. The 3-input production path uses a
smooth ISA ambient-temperature surrogate so the calibrated CSV can be queried
continuously without inventing a fired-cycle power model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import Delaunay, QhullError


CSV_PATH = Path(__file__).resolve().parents[1] / "rotax_915is_performance_map.csv"

REQUIRED_COLUMNS = [
    "case_no",
    "rpm",
    "throttle_pct",
    "alt_ft",
    "t_amb_C",
    "power_kW",
    "fuelflow_kgh",
    "p_plenum_bar",
    "t_plenum_K",
]

OUTPUT_COLUMNS = [
    "power_kW",
    "fuelflow_kgh",
    "p_plenum_bar",
    "t_plenum_K",
]

PRODUCTION_SOURCE = "calibrated_csv"
PHYSICS_SOURCE = "cantera_physics_derived"
VALIDATION_STATUS_VALIDATED = "validated_csv"
VALIDATION_STATUS_EXPERIMENTAL = "experimental_unvalidated"


def isa_temp_c(alt_ft: float) -> float:
    """Approximate ISA temperature in degC below the tropopause."""
    return 15.0 - 1.98 * (float(alt_ft) / 1000.0)


@dataclass(frozen=True)
class EngineOutputResult:
    rpm: float
    throttle_pct: float
    altitude_ft: float
    ambient_temp_C: float
    ambient_source: str
    case_no: int | None
    power_kW: float
    torque_Nm: float
    fuelflow_kgh: float
    p_plenum_bar: float
    t_plenum_K: float
    production_source: str
    physics_source: str
    validation_status: str
    exact: bool
    interpolated: bool
    extrapolated: bool


@dataclass(frozen=True)
class SupportingPhysicsFeatures:
    peak_cylinder_pressure_bar: float | None
    peak_cylinder_temperature_K: float | None
    compression_pressure_bar: float | None
    heat_release_J: float | None
    combustion_duration_deg: float | None
    combustion_phasing_deg: float | None
    relative_pressure_change_bar: float | None
    relative_temperature_change_K: float | None
    production_source: str
    physics_source: str
    validation_status: str


@dataclass(frozen=True)
class EngineState:
    rpm: float
    throttle_pct: float
    altitude_ft: float
    ambient_temp_C: float
    ambient_source: str
    power_kW: float
    torque_Nm: float
    fuelflow_kgh: float
    p_plenum_bar: float
    t_plenum_K: float
    fuel_mass_mg_per_cylinder_cycle: float
    production_source: str
    physics_source: str
    validation_status: str
    exact: bool
    interpolated: bool
    extrapolated: bool


def torque_nm_from_power_kw(power_kW: float, rpm: float) -> float:
    """Convert power to torque using the standard P = tau * omega relation."""
    omega_rad_s = 2.0 * pi * (float(rpm) / 60.0)
    return float(power_kW) * 1000.0 / omega_rad_s


def fuel_mass_mg_per_cylinder_cycle_from_fuelflow(
    fuelflow_kgh: float,
    rpm: float,
    cylinders: int = 4,
) -> float:
    """Simple downstream fuel-injection proxy derived from authoritative CSV fuel flow."""
    if cylinders <= 0:
        raise ValueError("cylinders must be positive")
    rpm = float(rpm)
    if rpm <= 0.0:
        raise ValueError("rpm must be positive")
    cycles_per_second_per_cylinder = rpm / 120.0
    fuel_kg_s = float(fuelflow_kgh) / 3600.0
    return fuel_kg_s / float(cylinders) / cycles_per_second_per_cylinder * 1e6


class Stage13HybridEngineOutput:
    """
    Read-only hybrid output layer for Stage 1.3.

    Absolute outputs come from the Rotax CSV. Cantera-derived values are kept
    separate and explicitly labeled as supporting physics.
    """

    def __init__(self, csv_path: str | Path = CSV_PATH):
        self.csv_path = Path(csv_path)
        self.df = pd.read_csv(self.csv_path)
        self._validate_schema()
        self._validate_numeric_columns()
        self._build_interpolators()

    def _validate_schema(self) -> None:
        missing = [col for col in REQUIRED_COLUMNS if col not in self.df.columns]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")

    def _validate_numeric_columns(self) -> None:
        numeric_cols = [
            "case_no",
            "rpm",
            "throttle_pct",
            "alt_ft",
            "t_amb_C",
            "power_kW",
            "fuelflow_kgh",
            "p_plenum_bar",
            "t_plenum_K",
        ]
        for col in numeric_cols:
            self.df[col] = pd.to_numeric(self.df[col], errors="raise")
        if self.df[numeric_cols].isna().any().any():
            raise ValueError("CSV contains NaN values in required columns.")

    def _build_interpolators(self) -> None:
        self._axis_ranges = {
            "rpm": (float(self.df["rpm"].min()), float(self.df["rpm"].max())),
            "throttle_pct": (
                float(self.df["throttle_pct"].min()),
                float(self.df["throttle_pct"].max()),
            ),
            "alt_ft": (float(self.df["alt_ft"].min()), float(self.df["alt_ft"].max())),
            "t_amb_C": (float(self.df["t_amb_C"].min()), float(self.df["t_amb_C"].max())),
        }

        coords = ["rpm", "throttle_pct", "alt_ft", "t_amb_C"]
        dup_groups = self.df[self.df.duplicated(subset=coords, keep=False)].copy()
        if not dup_groups.empty:
            conflicts = []
            for key, group in dup_groups.groupby(coords):
                first = group[OUTPUT_COLUMNS].iloc[0]
                equal = all(
                    np.allclose(group[col].to_numpy(dtype=float), first[col])
                    for col in OUTPUT_COLUMNS
                )
                if not equal:
                    conflicts.append((key, group.index.tolist()))
            if conflicts:
                raise ValueError(
                    "Conflicting duplicate operating points detected: "
                    + ", ".join(f"{key} idx={idxs}" for key, idxs in conflicts)
                )
            self._df_model = self.df.drop_duplicates(subset=coords, keep="first").reset_index(drop=True)
        else:
            self._df_model = self.df.copy()

        points_norm = self._normalize_points(
            self._df_model["rpm"].to_numpy(),
            self._df_model["throttle_pct"].to_numpy(),
            self._df_model["alt_ft"].to_numpy(),
            self._df_model["t_amb_C"].to_numpy(),
        )

        try:
            self._hull = Delaunay(points_norm)
        except QhullError as exc:
            raise ValueError(
                "Could not construct a convex hull from the Rotax reference data."
            ) from exc

        self._linear_interp = {
            col: LinearNDInterpolator(points_norm, self._df_model[col].to_numpy())
            for col in OUTPUT_COLUMNS
        }
    def _normalize_points(self, rpm, throttle, alt, tamb):
        def norm(vals, key):
            lo, hi = self._axis_ranges[key]
            if hi == lo:
                raise ValueError(f"Axis {key} has zero range.")
            return (np.asarray(vals, dtype=float) - lo) / (hi - lo)

        return np.column_stack(
            [
                norm(rpm, "rpm"),
                norm(throttle, "throttle_pct"),
                norm(alt, "alt_ft"),
                norm(tamb, "t_amb_C"),
            ]
        )

    def _constrained_slice_interpolate(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float,
    ):
        df = self._df_model.copy()

        rpm = float(rpm)
        throttle_pct = float(throttle_pct)
        altitude_ft = float(altitude_ft)
        ambient_temp_C = float(ambient_temp_C)

        for key, value in (
            ("rpm", rpm),
            ("throttle_pct", throttle_pct),
            ("alt_ft", altitude_ft),
            ("t_amb_C", ambient_temp_C),
        ):
            lo, hi = self._axis_ranges[key]
            if value < lo or value > hi:
                return None

        df_isa = 15.0 - (1.98 / 1000.0) * df["alt_ft"].to_numpy(float)
        df_offset = df["t_amb_C"].to_numpy(float) - df_isa

        requested_isa = 15.0 - (1.98 / 1000.0) * altitude_ft
        requested_offset = ambient_temp_C - requested_isa

        bands = np.array([0.0, 15.0, 30.0, 45.0], dtype=float)
        band = float(bands[np.argmin(np.abs(bands - requested_offset))])

        if abs(band - requested_offset) > 0.5:
            return None

        temp_mask = np.isclose(
            df_offset,
            band,
            rtol=0.0,
            atol=0.5,
        )

        df = df.loc[temp_mask].copy()

        if df.empty:
            return None

        rpm_levels = np.sort(
            df["rpm"].drop_duplicates().to_numpy(dtype=float)
        )

        lower_rpm = rpm_levels[rpm_levels <= rpm + 1e-9]
        upper_rpm = rpm_levels[rpm_levels >= rpm - 1e-9]

        if len(lower_rpm) == 0 or len(upper_rpm) == 0:
            return None

        rpm_lo = float(lower_rpm[-1])
        rpm_hi = float(upper_rpm[0])

        throttle_levels = np.sort(
            df["throttle_pct"].drop_duplicates().to_numpy(dtype=float)
        )

        lower_thr = throttle_levels[throttle_levels <= throttle_pct + 1e-9]
        upper_thr = throttle_levels[throttle_levels >= throttle_pct - 1e-9]

        if len(lower_thr) == 0 or len(upper_thr) == 0:
            return None

        thr_lo = float(lower_thr[-1])
        thr_hi = float(upper_thr[0])

        rpm_levels_needed = [rpm_lo] if np.isclose(rpm_lo, rpm_hi) else [rpm_lo, rpm_hi]
        thr_levels_needed = [thr_lo] if np.isclose(thr_lo, thr_hi) else [thr_lo, thr_hi]

        corner_values = {}

        for r in rpm_levels_needed:
            for thr in thr_levels_needed:
                corner = df[
                    np.isclose(df["rpm"].to_numpy(float), r, atol=1e-8)
                    & np.isclose(
                        df["throttle_pct"].to_numpy(float),
                        thr,
                        atol=1e-8,
                    )
                ][["alt_ft"] + OUTPUT_COLUMNS].copy()

                if len(corner) < 2:
                    return None

                corner = (
                    corner
                    .drop_duplicates(subset=["alt_ft"])
                    .sort_values("alt_ft")
                )

                alt = corner["alt_ft"].to_numpy(dtype=float)

                if altitude_ft < alt.min() or altitude_ft > alt.max():
                    return None

                corner_values[(r, thr)] = {
                    col: float(
                        np.interp(
                            altitude_ft,
                            alt,
                            corner[col].to_numpy(dtype=float),
                        )
                    )
                    for col in OUTPUT_COLUMNS
                }

        def bilinear(v00, v10, v01, v11):
            if np.isclose(rpm_lo, rpm_hi):
                rpm_w = 0.0
            else:
                rpm_w = (rpm - rpm_lo) / (rpm_hi - rpm_lo)

            if np.isclose(thr_lo, thr_hi):
                thr_w = 0.0
            else:
                thr_w = (throttle_pct - thr_lo) / (thr_hi - thr_lo)

            a = v00 * (1.0 - rpm_w) + v10 * rpm_w
            b = v01 * (1.0 - rpm_w) + v11 * rpm_w

            return a * (1.0 - thr_w) + b * thr_w

        values = {}

        for col in OUTPUT_COLUMNS:
            v00 = corner_values[(rpm_lo, thr_lo)][col]
            v10 = corner_values[(rpm_hi, thr_lo)][col]
            v01 = corner_values[(rpm_lo, thr_hi)][col]
            v11 = corner_values[(rpm_hi, thr_hi)][col]

            values[col] = float(
                bilinear(v00, v10, v01, v11)
            )

        return values

    def _validate_inputs(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float,
    ) -> None:
        checks = [
            ("rpm", rpm),
            ("throttle_pct", throttle_pct),
            ("alt_ft", altitude_ft),
            ("t_amb_C", ambient_temp_C),
        ]
        for key, value in checks:
            lo, hi = self._axis_ranges[key]
            if not (lo <= float(value) <= hi):
                raise ValueError(
                    f"{key}={value} is outside the calibrated CSV envelope "
                    f"[{lo}, {hi}]."
                )

    def _point_norm(self, rpm: float, throttle_pct: float, altitude_ft: float, ambient_temp_C: float) -> np.ndarray:
        return self._normalize_points([rpm], [throttle_pct], [altitude_ft], [ambient_temp_C])

    def _default_ambient_temp(self, altitude_ft: float) -> float:
        """
        Deterministic ambient surrogate for 3-input production queries.

        The CSV remains the authority for power, torque, fuel flow, and plenum
        conditions. This only supplies a smooth ambient-temperature coordinate
        so the 4D calibrated CSV surface can be queried from altitude.
        """

        return isa_temp_c(float(altitude_ft))

    def coverage_report(self) -> str:
        lines = [
            "Stage 1.3 hybrid engine-output coverage",
            f"  File: {self.csv_path}",
            f"  Rows: {len(self.df)}",
            f"  RPM: {sorted(self.df['rpm'].unique().tolist())}",
            f"  Throttle %: {sorted(self.df['throttle_pct'].unique().tolist())}",
            f"  Altitude ft: {sorted(self.df['alt_ft'].unique().tolist())}",
            f"  Ambient temperature C: {sorted(self.df['t_amb_C'].unique().tolist())}",
        ]
        return "\n".join(lines)

    def find_exact_rows(
        self,
        *,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float,
    ) -> pd.DataFrame:
        mask = (
            np.isclose(self.df["rpm"], rpm)
            & np.isclose(self.df["throttle_pct"], throttle_pct)
            & np.isclose(self.df["alt_ft"], altitude_ft)
            & np.isclose(self.df["t_amb_C"], ambient_temp_C)
        )
        return self.df.loc[mask].copy()

    def query(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float | None = None,
        *,
        mode: Literal["production", "validation", "boundary"] = "production",
    ) -> EngineOutputResult:
        if mode not in {"production", "validation", "boundary"}:
            raise ValueError("mode must be 'production', 'validation', or 'boundary'")

        if ambient_temp_C is None:
            ambient_temp_C = self._default_ambient_temp(altitude_ft)
            ambient_source = "isa_surrogate"
        else:
            ambient_source = "explicit_input"

        self._validate_inputs(rpm, throttle_pct, altitude_ft, ambient_temp_C)

        exact_rows = self.find_exact_rows(
            rpm=rpm,
            throttle_pct=throttle_pct,
            altitude_ft=altitude_ft,
            ambient_temp_C=ambient_temp_C,
        )
        if len(exact_rows) > 0:
            row = exact_rows.iloc[0]
            power_kw = float(row["power_kW"])
            return EngineOutputResult(
                rpm=float(rpm),
                throttle_pct=float(throttle_pct),
                altitude_ft=float(altitude_ft),
                ambient_temp_C=float(ambient_temp_C),
                ambient_source=ambient_source,
                case_no=int(row["case_no"]),
                power_kW=power_kw,
                torque_Nm=torque_nm_from_power_kw(power_kw, rpm),
                fuelflow_kgh=float(row["fuelflow_kgh"]),
                p_plenum_bar=float(row["p_plenum_bar"]),
                t_plenum_K=float(row["t_plenum_K"]),
                production_source=PRODUCTION_SOURCE,
                physics_source=PHYSICS_SOURCE,
                validation_status=VALIDATION_STATUS_VALIDATED,
                exact=True,
                interpolated=False,
                extrapolated=False,
            )

        point_norm = self._point_norm(rpm, throttle_pct, altitude_ft, ambient_temp_C)
        in_hull = bool(self._hull.find_simplex(point_norm)[0] >= 0)
        if not in_hull:
            values = self._constrained_slice_interpolate(
                rpm,
                throttle_pct,
                altitude_ft,
                ambient_temp_C,
            )
            if values is None:
                raise ValueError(
                    "Operating point is outside the calibrated CSV convex hull; "
                    "extrapolation is disabled."
                )
            interpolated = True
        else:
            values = {}
            interpolated = False

            for col in OUTPUT_COLUMNS:
                interp_value = self._linear_interp[col](point_norm)
                value = float(np.asarray(interp_value).ravel()[0])
                if np.isfinite(value):
                    values[col] = value
                    interpolated = True
                else:
                    raise ValueError(
                        f"Linear interpolation failed for {col} at the calibrated "
                        "CSV operating point."
                    )

        power_kw = values["power_kW"]
        return EngineOutputResult(
            rpm=float(rpm),
            throttle_pct=float(throttle_pct),
            altitude_ft=float(altitude_ft),
            ambient_temp_C=float(ambient_temp_C),
            ambient_source=ambient_source,
            case_no=None,
            power_kW=power_kw,
            torque_Nm=torque_nm_from_power_kw(power_kw, rpm),
            fuelflow_kgh=values["fuelflow_kgh"],
            p_plenum_bar=values["p_plenum_bar"],
            t_plenum_K=values["t_plenum_K"],
            production_source=PRODUCTION_SOURCE,
            physics_source=PHYSICS_SOURCE,
            validation_status=VALIDATION_STATUS_VALIDATED if interpolated else VALIDATION_STATUS_EXPERIMENTAL,
            exact=False,
            interpolated=interpolated,
            extrapolated=False,
        )

    def get_engine_state(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float | None = None,
        *,
        mode: Literal["production", "validation", "boundary"] = "production",
    ) -> EngineState:
        """Return the Stage 2 engine state on top of the calibrated CSV outputs."""

        result = self.query(
            rpm,
            throttle_pct,
            altitude_ft,
            ambient_temp_C,
            mode=mode,
        )
        return EngineState(
            rpm=result.rpm,
            throttle_pct=result.throttle_pct,
            altitude_ft=result.altitude_ft,
            ambient_temp_C=result.ambient_temp_C,
            ambient_source=result.ambient_source,
            power_kW=result.power_kW,
            torque_Nm=result.torque_Nm,
            fuelflow_kgh=result.fuelflow_kgh,
            p_plenum_bar=result.p_plenum_bar,
            t_plenum_K=result.t_plenum_K,
            fuel_mass_mg_per_cylinder_cycle=fuel_mass_mg_per_cylinder_cycle_from_fuelflow(
                result.fuelflow_kgh,
                result.rpm,
            ),
            production_source=result.production_source,
            physics_source=result.physics_source,
            validation_status=result.validation_status,
            exact=result.exact,
            interpolated=result.interpolated,
            extrapolated=result.extrapolated,
        )

    def query_by_case_no(self, case_no: int) -> EngineOutputResult:
        rows = self.df.loc[self.df["case_no"] == case_no]
        if len(rows) != 1:
            raise ValueError(f"Expected exactly one row for case_no={case_no}, found {len(rows)}.")
        row = rows.iloc[0]
        return self.query(
            float(row["rpm"]),
            float(row["throttle_pct"]),
            float(row["alt_ft"]),
            float(row["t_amb_C"]),
            mode="validation",
        )

    def select_exact_rows(self, count: int) -> pd.DataFrame:
        cols = ["case_no", "rpm", "throttle_pct", "alt_ft", "t_amb_C"]
        return self.df.sort_values(cols).head(count).copy()

    def build_supporting_physics_features(
        self,
        *,
        baseline_summary: dict | None = None,
        combustion_summary: dict | None = None,
    ) -> SupportingPhysicsFeatures:
        """
        Package Cantera-derived supporting features without using them as
        production authority.

        The caller decides whether to supply a validated no-combustion baseline
        or an experimental combustion summary. This keeps the feature layer
        separate from the calibrated CSV outputs.
        """

        peak_pressure_bar = None
        peak_temperature_K = None
        compression_pressure_bar = None
        heat_release_J = None
        combustion_duration_deg = None
        combustion_phasing_deg = None

        if baseline_summary is not None:
            compression_pressure_bar = float(baseline_summary.get("p_at_tdc_Pa", np.nan)) / 1e5
            peak_pressure_bar = compression_pressure_bar
            peak_temperature_K = float(baseline_summary.get("t_at_tdc_K", np.nan))
            heat_release_J = 0.0

        if combustion_summary is not None:
            peak_pressure_bar = float(combustion_summary.get("peak_pressure_pa", np.nan)) / 1e5
            peak_temperature_K = float(combustion_summary.get("peak_temperature_k", np.nan))
            heat_release_J = float(combustion_summary.get("integrated_heat_release_j", np.nan))
            combustion_duration_deg = float(
                combustion_summary.get(
                    "burn_end_deg", np.nan
                )
            ) - float(combustion_summary.get("burn_start_deg", np.nan))
            combustion_phasing_deg = float(combustion_summary.get("ignition_center_deg", np.nan))

        relative_pressure_change_bar = None
        relative_temperature_change_K = None
        if (
            peak_pressure_bar is not None
            and compression_pressure_bar is not None
            and np.isfinite(peak_pressure_bar)
            and np.isfinite(compression_pressure_bar)
        ):
            relative_pressure_change_bar = peak_pressure_bar - compression_pressure_bar
        if (
            peak_temperature_K is not None
            and baseline_summary is not None
            and np.isfinite(peak_temperature_K)
            and np.isfinite(float(baseline_summary.get("t_at_tdc_K", np.nan)))
        ):
            relative_temperature_change_K = peak_temperature_K - float(baseline_summary.get("t_at_tdc_K", np.nan))

        return SupportingPhysicsFeatures(
            peak_cylinder_pressure_bar=peak_pressure_bar,
            peak_cylinder_temperature_K=peak_temperature_K,
            compression_pressure_bar=compression_pressure_bar,
            heat_release_J=heat_release_J,
            combustion_duration_deg=combustion_duration_deg,
            combustion_phasing_deg=combustion_phasing_deg,
            relative_pressure_change_bar=relative_pressure_change_bar,
            relative_temperature_change_K=relative_temperature_change_K,
            production_source=PRODUCTION_SOURCE,
            physics_source=PHYSICS_SOURCE,
            validation_status=(
                VALIDATION_STATUS_VALIDATED if combustion_summary is None else VALIDATION_STATUS_EXPERIMENTAL
            ),
        )


def main() -> int:
    model = Stage13HybridEngineOutput()
    print(model.coverage_report())
    return 0


def get_engine_state(
    rpm: float,
    throttle_pct: float,
    altitude_ft: float,
    ambient_temp_C: float | None = None,
    *,
    mode: Literal["production", "validation", "boundary"] = "production",
    csv_path: str | Path = CSV_PATH,
) -> EngineState:
    """Convenience wrapper for downstream Stage 2 callers."""

    return Stage13HybridEngineOutput(csv_path).get_engine_state(
        rpm,
        throttle_pct,
        altitude_ft,
        ambient_temp_C,
        mode=mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
