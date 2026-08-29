"""
Stage 3 simplified altitude performance profile.

This script stays within the validated Stage 2 interface and produces a clean
altitude sweep across the calibrated envelope only. The Rotax CSV/interpolator
remains the production authority.
"""

from __future__ import annotations

import hashlib
from math import isfinite
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from stage1_3_hybrid_engine_output import CSV_PATH, Stage13HybridEngineOutput


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "engine_model" / "stage3_outputs"
ALTITUDE_POINTS_FT = [0, 5000, 10000, 15000, 17000, 20000, 22999]
REQUESTED_OUT_OF_ENVELOPE_FT = 23000
SELECTED_RPM = 5800.0
SELECTED_THROTTLE = 100.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_protected_files() -> dict[str, str]:
    protected_patterns = [
        "engine_model/stage1_2_*.py",
        "engine_model/wall_closed_compression_verified.py",
        "rotax_915is_performance_map.csv",
        "calibration/*.csv",
        "calibration/*.json",
        "config/rotax_915is_engine_parameters.csv",
        "config/rotax_915is_engine_parameters.md",
        "config/rotax_915is_missing_parameters.md",
    ]
    snapshot: dict[str, str] = {}
    for pattern in protected_patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                snapshot[str(path.relative_to(ROOT))] = _sha256(path)
    return snapshot


def _assert_finite(name: str, value: float) -> None:
    if not isfinite(float(value)):
        raise AssertionError(f"{name} must be finite")


def _trend_pct(value: float, sea_level: float) -> float:
    return (float(value) - float(sea_level)) / float(sea_level) * 100.0


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _save_plot(x, y, ylabel: str, filename: str, title: str) -> Path:
    _ensure_output_dir()
    path = OUTPUT_DIR / filename
    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=160)
    ax.plot(x, y, marker="o", linewidth=2.0)
    ax.set_xlabel("Altitude (ft)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _validate_selected_operating_point(model: Stage13HybridEngineOutput) -> None:
    for alt in ALTITUDE_POINTS_FT:
        state = model.get_engine_state(SELECTED_RPM, SELECTED_THROTTLE, float(alt))
        _assert_finite("power_kW", state.power_kW)
        _assert_finite("torque_Nm", state.torque_Nm)
        _assert_finite("fuelflow_kgh", state.fuelflow_kgh)
        _assert_finite("p_plenum_bar", state.p_plenum_bar)
        _assert_finite("t_plenum_K", state.t_plenum_K)
        if state.extrapolated:
            raise AssertionError(f"Silent extrapolation detected at altitude {alt} ft")


def main() -> int:
    before = _snapshot_protected_files()
    model = Stage13HybridEngineOutput()

    print("=" * 94)
    print("STAGE 3 ALTITUDE PERFORMANCE PROFILE")
    print("=" * 94)
    print(f"CSV calibrated envelope maximum = {int(model.df['alt_ft'].max())} ft")
    print(f"Requested out-of-envelope point = {REQUESTED_OUT_OF_ENVELOPE_FT} ft")
    try:
        model.get_engine_state(SELECTED_RPM, SELECTED_THROTTLE, float(REQUESTED_OUT_OF_ENVELOPE_FT))
    except ValueError as exc:
        print(f"23000 ft requested point = outside envelope: {exc}")
        print("23000 ft was not extrapolated or used.")
    else:
        raise AssertionError("23000 ft must be rejected as outside the calibrated envelope.")

    _validate_selected_operating_point(model)
    print(f"Selected RPM = {SELECTED_RPM:.0f}")
    print(f"Selected throttle = {SELECTED_THROTTLE:.1f}")

    rows = []
    for alt in ALTITUDE_POINTS_FT:
        state = model.get_engine_state(SELECTED_RPM, SELECTED_THROTTLE, float(alt))
        row = {
            "altitude_ft": float(alt),
            "rpm": state.rpm,
            "throttle_pct": state.throttle_pct,
            "power_kW": state.power_kW,
            "torque_Nm": state.torque_Nm,
            "fuelflow_kgh": state.fuelflow_kgh,
            "p_plenum_bar": state.p_plenum_bar,
            "t_plenum_K": state.t_plenum_K,
            "production_source": state.production_source,
            "physics_source": state.physics_source,
            "validation_status": state.validation_status,
            "exact": state.exact,
            "interpolated": state.interpolated,
            "extrapolated": state.extrapolated,
            "ambient_source": state.ambient_source,
        }
        rows.append(row)
        for key in ["power_kW", "torque_Nm", "fuelflow_kgh", "p_plenum_bar", "t_plenum_K"]:
            _assert_finite(key, row[key])
        if state.extrapolated:
            raise AssertionError(f"Silent extrapolation detected at altitude {alt} ft")
        if state.production_source != "calibrated_csv":
            raise AssertionError("Production source must remain calibrated_csv")
        if state.physics_source != "cantera_physics_derived":
            raise AssertionError("Physics source must remain cantera_physics_derived")

    profile = pd.DataFrame(rows)
    sea = profile.iloc[0]
    print("\nAltitude profile:")
    print(profile.to_string(index=False))

    print("\nAltitude trends relative to sea level:")
    for _, row in profile.iterrows():
        alt = int(row["altitude_ft"])
        power_change = _trend_pct(row["power_kW"], sea["power_kW"])
        torque_change = _trend_pct(row["torque_Nm"], sea["torque_Nm"])
        fuel_change = _trend_pct(row["fuelflow_kgh"], sea["fuelflow_kgh"])
        print(
            f"  {alt:5d} ft: power={power_change:+.3f} %, torque={torque_change:+.3f} %, "
            f"fuel_flow={fuel_change:+.3f} %, p_plenum={row['p_plenum_bar']:.4f} bar, "
            f"t_plenum={row['t_plenum_K']:.2f} K"
        )

    power_values = profile["power_kW"].to_list()
    deltas = [abs(power_values[i] - power_values[i - 1]) for i in range(1, len(power_values))]
    max_drop_index = max(range(1, len(power_values)), key=lambda i: power_values[i - 1] - power_values[i])
    strongest_drop_alt = int(profile.iloc[max_drop_index]["altitude_ft"])

    if power_values[0] >= power_values[1] >= power_values[2]:
        maintained_region = "not clearly maintained"
    elif power_values[0] <= power_values[1]:
        maintained_region = "initially maintained / slightly rising"
    else:
        maintained_region = "mixed"

    print("\nQualitative assessment:")
    print(f"  Maintained-power region: {maintained_region}")
    print(f"  Strongest power drop begins around: {strongest_drop_alt} ft")

    plot_paths = [
        _save_plot(profile["altitude_ft"], profile["power_kW"], "Power (kW)", "stage3_power_vs_altitude.png", "Stage 3 Power vs Altitude"),
        _save_plot(profile["altitude_ft"], profile["torque_Nm"], "Torque (N-m)", "stage3_torque_vs_altitude.png", "Stage 3 Torque vs Altitude"),
        _save_plot(profile["altitude_ft"], profile["fuelflow_kgh"], "Fuel flow (kg/h)", "stage3_fuel_flow_vs_altitude.png", "Stage 3 Fuel Flow vs Altitude"),
        _save_plot(profile["altitude_ft"], profile["p_plenum_bar"], "Plenum pressure (bar)", "stage3_plenum_pressure_vs_altitude.png", "Stage 3 Plenum Pressure vs Altitude"),
    ]

    print("\nPlot/output locations:")
    for path in plot_paths:
        print(f"  {path}")

    after = _snapshot_protected_files()
    if before != after:
        changed = sorted(set(before) ^ set(after))
        common = sorted(set(before) & set(after))
        modified = [path for path in common if before[path] != after[path]]
        raise AssertionError(
            "Protected file integrity failed: "
            f"added/removed={changed}, modified={modified}"
        )
    print(f"\nProtected files confirmed unchanged: {len(before)}")

    print("\nStage 3 validation: PASS")
    print("Ready for external real-value comparison: yes, after review of this internal profile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
