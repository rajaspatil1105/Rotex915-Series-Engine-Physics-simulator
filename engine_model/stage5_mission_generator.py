"""
Stage 5 time-series mission generator.

This module keeps the Stage 3 calibrated engine-output layer authoritative
while expanding the Stage 5 mission families around a reusable schedule and
mission-specific motion profile.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, pi, sin
from pathlib import Path
from random import Random

try:
    from stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, isa_temp_c
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, isa_temp_c

try:
    from stage5_mission_config import (
        MISSION_TYPE_ENDURANCE,
        MISSION_TYPE_HIGH_ALTITUDE,
        MISSION_TYPE_HIGH_POWER,
        MISSION_TYPE_HOT_WEATHER,
        MISSION_TYPE_NORMAL,
        MISSION_TYPE_RAPID_THROTTLE,
        MissionConfig,
        derive_normal_mission_durations,
    )
except ModuleNotFoundError:  # pragma: no cover - import compatibility shim
    from engine_model.stage5_mission_config import (
        MISSION_TYPE_ENDURANCE,
        MISSION_TYPE_HIGH_ALTITUDE,
        MISSION_TYPE_HIGH_POWER,
        MISSION_TYPE_HOT_WEATHER,
        MISSION_TYPE_NORMAL,
        MISSION_TYPE_RAPID_THROTTLE,
        MissionConfig,
        derive_normal_mission_durations,
    )


MISSION_PHASE_TAKEOFF = "TAKEOFF"
MISSION_PHASE_CLIMB = "CLIMB"
MISSION_PHASE_CRUISE = "CRUISE"
MISSION_PHASE_DESCENT = "DESCENT"
MISSION_PHASE_IDLE_LANDING = "IDLE/LANDING"
MISSION_PHASES = (
    MISSION_PHASE_TAKEOFF,
    MISSION_PHASE_CLIMB,
    MISSION_PHASE_CRUISE,
    MISSION_PHASE_DESCENT,
    MISSION_PHASE_IDLE_LANDING,
)

P0_HPA = 1013.25
T0_K = 288.15
LAPSE_K_PER_M = 0.0065
G0_M_PER_S2 = 9.80665
R_AIR_J_PER_KG_K = 287.05
ALTITUDE_LIMIT_FT = 23000.0
RPM_LIMIT = 5800.0
THROTTLE_MIN = 56.5
THROTTLE_MAX = 100.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def smootherstep_5(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def _blend(start_value: float, end_value: float, start_s: float, end_s: float, t_s: float) -> float:
    if end_s <= start_s:
        return float(end_value)
    fraction = smootherstep_5((float(t_s) - float(start_s)) / (float(end_s) - float(start_s)))
    return float(start_value) + fraction * (float(end_value) - float(start_value))


def _sequence_value(progress: float, control_points: tuple[float, ...], values: tuple[float, ...]) -> float:
    if len(control_points) != len(values):
        raise ValueError("control_points and values must have the same length")
    if not control_points:
        raise ValueError("control_points must not be empty")
    if progress <= control_points[0]:
        return float(values[0])
    for idx in range(len(control_points) - 1):
        start_p = control_points[idx]
        end_p = control_points[idx + 1]
        if progress <= end_p:
            if end_p <= start_p:
                return float(values[idx + 1])
            local = (progress - start_p) / (end_p - start_p)
            return _blend(values[idx], values[idx + 1], 0.0, 1.0, local)
    return float(values[-1])


def isa_pressure_hpa(altitude_ft: float) -> float:
    """Canonical ISA pressure surrogate for the Stage 5 environment model."""

    altitude_ft = float(altitude_ft)
    if altitude_ft < 0.0:
        raise ValueError("altitude_ft must be non-negative")
    altitude_m = altitude_ft * 0.3048
    if altitude_m > 11000.0:
        raise ValueError("isa_pressure_hpa currently supports altitudes up to 11 km.")
    temperature_k = T0_K - LAPSE_K_PER_M * altitude_m
    exponent = G0_M_PER_S2 / (R_AIR_J_PER_KG_K * LAPSE_K_PER_M)
    return P0_HPA * (temperature_k / T0_K) ** exponent


@dataclass(frozen=True)
class MissionState:
    time_s: float
    mission_id: str
    mission_type: str
    phase: str
    altitude_ft: float
    altitude_m: float
    ambient_temperature_C: float
    ambient_pressure_hPa: float
    rpm: float
    throttle_pct: float
    power_kW: float | None = None
    torque_Nm: float | None = None
    fuelflow_kgh: float | None = None
    p_plenum_bar: float | None = None
    t_plenum_K: float | None = None
    random_seed: int | None = None
    source_type: str = "python_generated"
    model_version: str = "stage5_mission_generator"
    mission_generated_values: str = "python_mission_generator"
    stage3_values: str = "csv_authoritative"
    stage3_validation_status: str | None = None
    ambient_source: str = "python_generated_isa_plus_offset"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MissionSchedule:
    takeoff_end_s: float
    climb_end_s: float
    cruise_end_s: float
    descent_end_s: float
    mission_end_s: float
    takeoff_altitude_ft: float
    climb_altitude_ft: float
    cruise_altitude_ft: float
    descent_altitude_ft: float
    takeoff_duration_s: float
    climb_duration_s: float
    cruise_duration_s: float
    descent_duration_s: float
    landing_duration_s: float


def _build_schedule(config: MissionConfig) -> MissionSchedule:
    altitude_delta_ft = max(0.0, config.target_altitude_ft - config.initial_altitude_ft)
    if config.mission_type == MISSION_TYPE_NORMAL:
        durations = derive_normal_mission_durations(
            initial_altitude_ft=config.initial_altitude_ft,
            target_altitude_ft=config.target_altitude_ft,
            climb_rate_fpm=config.climb_rate_fpm,
            descent_rate_fpm=config.descent_rate_fpm,
            cruise_duration_s=config.cruise_duration_s,
            random_seed=config.random_seed,
        )
        if abs(durations["total_duration_s"] - config.total_duration_s) > max(
            1e-6,
            1e-9 * durations["total_duration_s"],
        ):
            raise ValueError("MissionConfig.total_duration_s does not match the derived Normal mission timing.")
        takeoff_duration_s = durations["takeoff_duration_s"]
        climb_duration_s = durations["climb_duration_s"]
        cruise_duration_s = durations["cruise_duration_s"]
        descent_duration_s = durations["descent_duration_s"]
        landing_duration_s = durations["landing_duration_s"]
    else:
        takeoff_duration_s = float(config.takeoff_duration_s)
        climb_duration_s = max(60.0, altitude_delta_ft / float(config.climb_rate_fpm) * 60.0)
        cruise_duration_s = max(0.0, float(config.cruise_duration_s))
        descent_duration_s = max(60.0, altitude_delta_ft / float(config.descent_rate_fpm) * 60.0)
        landing_duration_s = max(15.0, float(config.transition_duration_s))
        derived_total = (
            takeoff_duration_s
            + climb_duration_s
            + cruise_duration_s
            + descent_duration_s
            + landing_duration_s
        )
        if abs(derived_total - config.total_duration_s) > max(1e-6, 1e-9 * derived_total):
            raise ValueError("MissionConfig.total_duration_s does not match the configured mission timing.")

    takeoff_end_s = takeoff_duration_s
    climb_end_s = takeoff_end_s + climb_duration_s
    cruise_end_s = climb_end_s + cruise_duration_s
    descent_end_s = cruise_end_s + descent_duration_s
    mission_end_s = descent_end_s + landing_duration_s
    takeoff_altitude_ft = config.initial_altitude_ft + 0.15 * altitude_delta_ft

    return MissionSchedule(
        takeoff_end_s=takeoff_end_s,
        climb_end_s=climb_end_s,
        cruise_end_s=cruise_end_s,
        descent_end_s=descent_end_s,
        mission_end_s=mission_end_s,
        takeoff_altitude_ft=takeoff_altitude_ft,
        climb_altitude_ft=config.target_altitude_ft,
        cruise_altitude_ft=config.target_altitude_ft,
        descent_altitude_ft=config.initial_altitude_ft,
        takeoff_duration_s=takeoff_duration_s,
        climb_duration_s=climb_duration_s,
        cruise_duration_s=cruise_duration_s,
        descent_duration_s=descent_duration_s,
        landing_duration_s=landing_duration_s,
    )


def _phase_for_time(t_s: float, schedule: MissionSchedule) -> str:
    if t_s < schedule.takeoff_end_s:
        return MISSION_PHASE_TAKEOFF
    if t_s < schedule.climb_end_s:
        return MISSION_PHASE_CLIMB
    if t_s < schedule.cruise_end_s:
        return MISSION_PHASE_CRUISE
    if t_s < schedule.descent_end_s:
        return MISSION_PHASE_DESCENT
    return MISSION_PHASE_IDLE_LANDING


class NormalMissionGenerator:
    """Generate seeded mission profiles for all supported Stage 5 mission types."""

    def __init__(
        self,
        mission_config: MissionConfig,
        *,
        engine_model: Stage13HybridEngineOutput | None = None,
    ) -> None:
        mission_config.validate()
        self.config = mission_config
        self.schedule = _build_schedule(mission_config)
        self.engine_model = engine_model or Stage13HybridEngineOutput()
        self._seed_rng = Random(int(self.config.random_seed))
        self._rapid_throttle_offset = self._seed_rng.uniform(0.0, 2.0 * pi)
        self._endurance_offset = self._seed_rng.uniform(0.0, 2.0 * pi)

    def _validate_time(self, t_s: float) -> float:
        t_s = float(t_s)
        if not isfinite(t_s):
            raise ValueError("t must be finite")
        if t_s < 0.0 or t_s > self.schedule.mission_end_s:
            raise ValueError("Requested mission time is outside the configured mission window.")
        return t_s

    def _phase_bounds(self, phase: str) -> tuple[float, float]:
        if phase == MISSION_PHASE_TAKEOFF:
            return 0.0, self.schedule.takeoff_end_s
        if phase == MISSION_PHASE_CLIMB:
            return self.schedule.takeoff_end_s, self.schedule.climb_end_s
        if phase == MISSION_PHASE_CRUISE:
            return self.schedule.climb_end_s, self.schedule.cruise_end_s
        if phase == MISSION_PHASE_DESCENT:
            return self.schedule.cruise_end_s, self.schedule.descent_end_s
        return self.schedule.descent_end_s, self.schedule.mission_end_s

    def _phase_anchor_values(self, phase: str) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        cfg = self.config
        if phase == MISSION_PHASE_TAKEOFF:
            return (
                (cfg.takeoff_rpm, cfg.takeoff_throttle_pct),
                (cfg.climb_rpm, cfg.climb_throttle_pct),
                (cfg.initial_altitude_ft, self.schedule.takeoff_altitude_ft),
            )
        if phase == MISSION_PHASE_CLIMB:
            return (
                (cfg.climb_rpm, cfg.climb_throttle_pct),
                (cfg.cruise_rpm, cfg.cruise_throttle_pct),
                (self.schedule.takeoff_altitude_ft, self.schedule.climb_altitude_ft),
            )
        if phase == MISSION_PHASE_CRUISE:
            return (
                (cfg.cruise_rpm, cfg.cruise_throttle_pct),
                (cfg.cruise_rpm, cfg.cruise_throttle_pct),
                (self.schedule.cruise_altitude_ft, self.schedule.cruise_altitude_ft),
            )
        if phase == MISSION_PHASE_DESCENT:
            return (
                (cfg.cruise_rpm, cfg.cruise_throttle_pct),
                (cfg.descent_rpm, cfg.descent_throttle_pct),
                (self.schedule.cruise_altitude_ft, self.schedule.descent_altitude_ft),
            )
        return (
            (cfg.descent_rpm, cfg.descent_throttle_pct),
            (cfg.descent_rpm, cfg.descent_throttle_pct),
            (self.schedule.descent_altitude_ft, self.schedule.descent_altitude_ft),
        )

    def _phase_progress(self, phase: str, t_s: float) -> float:
        start_s, end_s = self._phase_bounds(phase)
        if end_s <= start_s:
            return 1.0
        raw = (float(t_s) - float(start_s)) / (float(end_s) - float(start_s))
        if self.config.mission_type == MISSION_TYPE_HIGH_POWER and phase == MISSION_PHASE_TAKEOFF:
            if raw <= 0.25:
                return 0.0
            return smootherstep_5((raw - 0.25) / 0.75)
        return smootherstep_5(raw)

    def _endurance_adjustments(
        self,
        phase: str,
        t_s: float,
        start_s: float,
        end_s: float,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
    ) -> tuple[float, float, float]:
        if phase != MISSION_PHASE_CRUISE:
            return rpm, throttle_pct, altitude_ft
        if end_s <= start_s:
            return rpm, throttle_pct, altitude_ft
        local = (float(t_s) - float(start_s)) / (float(end_s) - float(start_s))
        wave_1 = sin(2.0 * pi * (3.0 * local + self._endurance_offset))
        wave_2 = sin(2.0 * pi * (1.5 * local + self._endurance_offset / 2.0))
        rpm = rpm + 120.0 * wave_1
        throttle_pct = throttle_pct + 3.0 * wave_1
        altitude_ft = altitude_ft + 40.0 * wave_2
        return rpm, throttle_pct, altitude_ft

    def _rapid_throttle_profile(self, t_s: float) -> tuple[float, float]:
        progress = float(t_s) / float(self.schedule.mission_end_s)
        throttle = _sequence_value(
            progress,
            (0.00, 0.08, 0.17, 0.29, 0.42, 0.58, 0.73, 0.88, 1.00),
            (100.0, 72.0, 84.5, 100.0, 72.0, 97.4, 84.5, 56.5, 56.5),
        )
        rpm = _sequence_value(
            progress,
            (0.00, 0.08, 0.17, 0.29, 0.42, 0.58, 0.73, 0.88, 1.00),
            (5800.0, 5000.0, 5500.0, 5800.0, 5200.0, 5500.0, 5000.0, 3000.0, 3000.0),
        )
        return rpm, throttle

    def _generate_state_without_engine(self, t_s: float) -> tuple[str, float, float, float]:
        phase = _phase_for_time(t_s, self.schedule)
        start_s, end_s = self._phase_bounds(phase)
        (rpm_start, throttle_start), (rpm_end, throttle_end), (alt_start, alt_end) = self._phase_anchor_values(phase)

        progress = self._phase_progress(phase, t_s)
        rpm = rpm_start + progress * (rpm_end - rpm_start)
        throttle_pct = throttle_start + progress * (throttle_end - throttle_start)
        altitude_ft = alt_start + progress * (alt_end - alt_start)

        if self.config.mission_type == MISSION_TYPE_ENDURANCE:
            rpm, throttle_pct, altitude_ft = self._endurance_adjustments(
                phase,
                t_s,
                start_s,
                end_s,
                rpm,
                throttle_pct,
                altitude_ft,
            )
        elif self.config.mission_type == MISSION_TYPE_RAPID_THROTTLE:
            rpm, throttle_pct = self._rapid_throttle_profile(t_s)

        return phase, rpm, throttle_pct, altitude_ft

    def get_state(self, t_s: float) -> MissionState:
        t_s = self._validate_time(t_s)
        phase, rpm, throttle_pct, altitude_ft = self._generate_state_without_engine(t_s)
        if altitude_ft < -1e-9 or altitude_ft > ALTITUDE_LIMIT_FT + 1e-9:
            raise ValueError("Mission altitude exceeds the supported envelope.")
        if rpm < 0.0 or rpm > RPM_LIMIT + 1e-9:
            raise ValueError("Mission RPM exceeds the supported envelope.")
        if throttle_pct < THROTTLE_MIN - 1e-9 or throttle_pct > THROTTLE_MAX + 1e-9:
            raise ValueError("Mission throttle exceeds the supported envelope.")

        altitude_ft = max(0.0, altitude_ft)
        altitude_m = altitude_ft * 0.3048
        ambient_temperature_C = isa_temp_c(altitude_ft) + float(self.config.ambient_temperature_offset_C)
        ambient_pressure_hPa = isa_pressure_hpa(altitude_ft)
        engine_state = self.engine_model.get_engine_state(
            rpm,
            throttle_pct,
            altitude_ft,
            ambient_temperature_C,
        )
        return MissionState(
            time_s=t_s,
            mission_id=self.config.mission_id,
            mission_type=self.config.mission_type,
            phase=phase,
            altitude_ft=altitude_ft,
            altitude_m=altitude_m,
            ambient_temperature_C=ambient_temperature_C,
            ambient_pressure_hPa=ambient_pressure_hPa,
            rpm=engine_state.rpm,
            throttle_pct=engine_state.throttle_pct,
            power_kW=engine_state.power_kW,
            torque_Nm=engine_state.torque_Nm,
            fuelflow_kgh=engine_state.fuelflow_kgh,
            p_plenum_bar=engine_state.p_plenum_bar,
            t_plenum_K=engine_state.t_plenum_K,
            random_seed=self.config.random_seed,
            stage3_validation_status=engine_state.validation_status,
            ambient_source="python_generated_isa_plus_offset",
        )

    def generate_rows(self) -> list[MissionState]:
        rows: list[MissionState] = []
        step_s = float(self.config.timestep_s)
        mission_end_s = float(self.schedule.mission_end_s)
        if step_s <= 0.0:
            raise ValueError("timestep_s must be positive")

        # Sample on a fixed grid and stop at the last complete timestep.
        # This avoids emitting a fractional final row when the mission duration
        # is not an exact multiple of the configured timestep.
        t_s = 0.0
        while t_s <= mission_end_s + 1e-9:
            rows.append(self.get_state(t_s))
            t_s += step_s
            if t_s > mission_end_s:
                break
        return rows


def get_mission_state(t_s: float, mission_config: MissionConfig) -> MissionState:
    """Return the mission state for a single timestep."""

    return NormalMissionGenerator(mission_config).get_state(t_s)


def generate_normal_mission_rows(
    mission_config: MissionConfig,
    *,
    engine_model: Stage13HybridEngineOutput | None = None,
) -> list[MissionState]:
    generator = NormalMissionGenerator(mission_config, engine_model=engine_model)
    return generator.generate_rows()


def write_mission_csv(rows: list[MissionState], csv_path: str | Path) -> Path:
    import csv

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].to_dict().keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
    return csv_path
