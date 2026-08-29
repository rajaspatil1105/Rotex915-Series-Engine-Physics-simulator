"""
Stage 5 mission configuration for the Rotax 915 iS simulator.

This module keeps mission inputs explicit, source-grounded, and deterministic.
The same config shape is reused across all Stage 5 mission families.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from random import Random
from typing import Literal


MISSION_TYPE_NORMAL = "NORMAL"
MISSION_TYPE_HIGH_ALTITUDE = "HIGH_ALTITUDE"
MISSION_TYPE_ENDURANCE = "ENDURANCE"
MISSION_TYPE_HOT_WEATHER = "HOT_WEATHER"
MISSION_TYPE_HIGH_POWER = "HIGH_POWER"
MISSION_TYPE_RAPID_THROTTLE = "RAPID_THROTTLE"

SUPPORTED_MISSION_TYPES = (
    MISSION_TYPE_NORMAL,
    MISSION_TYPE_HIGH_ALTITUDE,
    MISSION_TYPE_ENDURANCE,
    MISSION_TYPE_HOT_WEATHER,
    MISSION_TYPE_HIGH_POWER,
    MISSION_TYPE_RAPID_THROTTLE,
)


@dataclass(frozen=True)
class MissionTemplate:
    mission_type: str
    mission_id_prefix: str
    initial_altitude_ft_range: tuple[float, float]
    target_altitude_ft_range: tuple[float, float]
    climb_rate_fpm_range: tuple[float, float]
    descent_rate_fpm_range: tuple[float, float]
    cruise_duration_s_range: tuple[float, float]
    takeoff_duration_s_range: tuple[float, float]
    transition_duration_s_range: tuple[float, float]
    ambient_temperature_offset_C_options: tuple[float, ...]
    takeoff_rpm: float
    takeoff_throttle_pct: float
    climb_rpm: float
    climb_throttle_pct: float
    cruise_rpm: float
    cruise_throttle_pct: float
    descent_rpm: float
    descent_throttle_pct: float
    notes: str = ""


@dataclass(frozen=True)
class MissionConfig:
    mission_id: str
    mission_type: Literal[
        "NORMAL",
        "HIGH_ALTITUDE",
        "ENDURANCE",
        "HOT_WEATHER",
        "HIGH_POWER",
        "RAPID_THROTTLE",
    ]
    timestep_s: float
    total_duration_s: float
    initial_altitude_ft: float
    target_altitude_ft: float
    climb_rate_fpm: float
    descent_rate_fpm: float
    cruise_duration_s: float
    takeoff_rpm: float
    takeoff_throttle_pct: float
    climb_rpm: float
    climb_throttle_pct: float
    cruise_rpm: float
    cruise_throttle_pct: float
    descent_rpm: float
    descent_throttle_pct: float
    ambient_temperature_offset_C: float
    random_seed: int
    takeoff_duration_s: float = 20.0
    transition_duration_s: float = 20.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def validate(self) -> None:
        if self.mission_type not in SUPPORTED_MISSION_TYPES:
            raise ValueError(f"Unsupported mission type: {self.mission_type}")
        if self.timestep_s <= 0.0:
            raise ValueError("timestep_s must be positive")
        if self.total_duration_s <= 0.0:
            raise ValueError("total_duration_s must be positive")
        if self.initial_altitude_ft < 0.0:
            raise ValueError("initial_altitude_ft must be non-negative")
        if self.target_altitude_ft < self.initial_altitude_ft:
            raise ValueError("target_altitude_ft must be >= initial_altitude_ft")
        if self.climb_rate_fpm <= 0.0:
            raise ValueError("climb_rate_fpm must be positive")
        if self.descent_rate_fpm <= 0.0:
            raise ValueError("descent_rate_fpm must be positive")
        if self.cruise_duration_s < 0.0:
            raise ValueError("cruise_duration_s must be non-negative")
        if self.takeoff_duration_s <= 0.0:
            raise ValueError("takeoff_duration_s must be positive")
        if self.transition_duration_s <= 0.0:
            raise ValueError("transition_duration_s must be positive")
        for name, value in {
            "takeoff_rpm": self.takeoff_rpm,
            "climb_rpm": self.climb_rpm,
            "cruise_rpm": self.cruise_rpm,
            "descent_rpm": self.descent_rpm,
        }.items():
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name, value in {
            "takeoff_throttle_pct": self.takeoff_throttle_pct,
            "climb_throttle_pct": self.climb_throttle_pct,
            "cruise_throttle_pct": self.cruise_throttle_pct,
            "descent_throttle_pct": self.descent_throttle_pct,
        }.items():
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be between 0 and 100")


def _sample_range(rng: Random, lo: float, hi: float, *, mode: float | None = None) -> float:
    lo = float(lo)
    hi = float(hi)
    if hi < lo:
        raise ValueError("Range upper bound must be >= lower bound")
    if hi == lo:
        return lo
    if mode is None:
        mode = (lo + hi) / 2.0
    return float(rng.triangular(lo, hi, float(mode)))


def _sample_choice(rng: Random, options: tuple[float, ...]) -> float:
    if not options:
        raise ValueError("options must not be empty")
    return float(options[rng.randrange(len(options))])


MISSION_TEMPLATES: dict[str, MissionTemplate] = {
    MISSION_TYPE_NORMAL: MissionTemplate(
        mission_type=MISSION_TYPE_NORMAL,
        mission_id_prefix="normal",
        initial_altitude_ft_range=(0.0, 0.0),
        target_altitude_ft_range=(10000.0, 10000.0),
        climb_rate_fpm_range=(1200.0, 1200.0),
        descent_rate_fpm_range=(1000.0, 1000.0),
        cruise_duration_s_range=(180.0, 180.0),
        takeoff_duration_s_range=(20.0, 20.0),
        transition_duration_s_range=(20.0, 20.0),
        ambient_temperature_offset_C_options=(0.0,),
        takeoff_rpm=5800.0,
        takeoff_throttle_pct=100.0,
        climb_rpm=5500.0,
        climb_throttle_pct=85.0,
        cruise_rpm=4600.0,
        cruise_throttle_pct=70.0,
        descent_rpm=3000.0,
        descent_throttle_pct=56.5,
        notes="Existing validated normal mission.",
    ),
    MISSION_TYPE_HIGH_ALTITUDE: MissionTemplate(
        mission_type=MISSION_TYPE_HIGH_ALTITUDE,
        mission_id_prefix="high_altitude",
        initial_altitude_ft_range=(0.0, 1000.0),
        target_altitude_ft_range=(15000.0, 22000.0),
        climb_rate_fpm_range=(1000.0, 1300.0),
        descent_rate_fpm_range=(900.0, 1100.0),
        cruise_duration_s_range=(120.0, 240.0),
        takeoff_duration_s_range=(18.0, 26.0),
        transition_duration_s_range=(16.0, 24.0),
        ambient_temperature_offset_C_options=(0.0,),
        takeoff_rpm=5800.0,
        takeoff_throttle_pct=100.0,
        climb_rpm=5500.0,
        climb_throttle_pct=85.0,
        cruise_rpm=4600.0,
        cruise_throttle_pct=70.0,
        descent_rpm=3000.0,
        descent_throttle_pct=56.5,
        notes="High-altitude climb/cruise scenario grounded in the critical-altitude range.",
    ),
    MISSION_TYPE_ENDURANCE: MissionTemplate(
        mission_type=MISSION_TYPE_ENDURANCE,
        mission_id_prefix="endurance",
        initial_altitude_ft_range=(0.0, 0.0),
        target_altitude_ft_range=(5000.0, 8000.0),
        climb_rate_fpm_range=(900.0, 1200.0),
        descent_rate_fpm_range=(800.0, 1100.0),
        cruise_duration_s_range=(900.0, 1800.0),
        takeoff_duration_s_range=(16.0, 24.0),
        transition_duration_s_range=(20.0, 35.0),
        ambient_temperature_offset_C_options=(0.0, 15.0),
        takeoff_rpm=5800.0,
        takeoff_throttle_pct=100.0,
        climb_rpm=5500.0,
        climb_throttle_pct=85.0,
        cruise_rpm=4600.0,
        cruise_throttle_pct=70.0,
        descent_rpm=3000.0,
        descent_throttle_pct=56.5,
        notes="Long-duration cruise with small bounded variations.",
    ),
    MISSION_TYPE_HOT_WEATHER: MissionTemplate(
        mission_type=MISSION_TYPE_HOT_WEATHER,
        mission_id_prefix="hot_weather",
        initial_altitude_ft_range=(5000.0, 8000.0),
        target_altitude_ft_range=(10000.0, 15000.0),
        climb_rate_fpm_range=(1000.0, 1300.0),
        descent_rate_fpm_range=(900.0, 1100.0),
        cruise_duration_s_range=(180.0, 300.0),
        takeoff_duration_s_range=(18.0, 24.0),
        transition_duration_s_range=(18.0, 26.0),
        ambient_temperature_offset_C_options=(15.0, 30.0),
        takeoff_rpm=5800.0,
        takeoff_throttle_pct=100.0,
        climb_rpm=5500.0,
        climb_throttle_pct=85.0,
        cruise_rpm=4600.0,
        cruise_throttle_pct=70.0,
        descent_rpm=3000.0,
        descent_throttle_pct=56.5,
        notes="Hot-weather offset scenarios using the canonical ISA surrogate.",
    ),
    MISSION_TYPE_HIGH_POWER: MissionTemplate(
        mission_type=MISSION_TYPE_HIGH_POWER,
        mission_id_prefix="high_power",
        initial_altitude_ft_range=(0.0, 1000.0),
        target_altitude_ft_range=(3000.0, 6000.0),
        climb_rate_fpm_range=(1000.0, 1400.0),
        descent_rate_fpm_range=(900.0, 1200.0),
        cruise_duration_s_range=(120.0, 240.0),
        takeoff_duration_s_range=(60.0, 300.0),
        transition_duration_s_range=(16.0, 24.0),
        ambient_temperature_offset_C_options=(0.0, 15.0),
        takeoff_rpm=5800.0,
        takeoff_throttle_pct=100.0,
        climb_rpm=5500.0,
        climb_throttle_pct=100.0,
        cruise_rpm=5500.0,
        cruise_throttle_pct=100.0,
        descent_rpm=3000.0,
        descent_throttle_pct=56.5,
        notes="Takeoff/high-power state held below the 5-minute limit.",
    ),
    MISSION_TYPE_RAPID_THROTTLE: MissionTemplate(
        mission_type=MISSION_TYPE_RAPID_THROTTLE,
        mission_id_prefix="rapid_throttle",
        initial_altitude_ft_range=(0.0, 500.0),
        target_altitude_ft_range=(0.0, 3000.0),
        climb_rate_fpm_range=(800.0, 1200.0),
        descent_rate_fpm_range=(800.0, 1200.0),
        cruise_duration_s_range=(240.0, 480.0),
        takeoff_duration_s_range=(20.0, 30.0),
        transition_duration_s_range=(8.0, 18.0),
        ambient_temperature_offset_C_options=(0.0, 15.0),
        takeoff_rpm=5800.0,
        takeoff_throttle_pct=100.0,
        climb_rpm=5200.0,
        climb_throttle_pct=70.0,
        cruise_rpm=4600.0,
        cruise_throttle_pct=70.0,
        descent_rpm=3000.0,
        descent_throttle_pct=56.5,
        notes="Deterministic throttle-ramp mission within the calibrated throttle envelope.",
    ),
}


def derive_normal_mission_durations(
    *,
    initial_altitude_ft: float,
    target_altitude_ft: float,
    climb_rate_fpm: float,
    descent_rate_fpm: float,
    cruise_duration_s: float,
    random_seed: int,
) -> dict[str, float]:
    """Derive smooth mission phase durations from the mission anchors."""

    altitude_delta_ft = max(0.0, float(target_altitude_ft) - float(initial_altitude_ft))
    rng = Random(int(random_seed))

    climb_base_s = altitude_delta_ft / float(climb_rate_fpm) * 60.0
    descent_base_s = altitude_delta_ft / float(descent_rate_fpm) * 60.0

    takeoff_duration_s = max(12.0, 20.0 + rng.uniform(-3.0, 3.0))
    climb_duration_s = max(60.0, climb_base_s + rng.uniform(-0.05, 0.05) * climb_base_s)
    cruise_duration_s = max(0.0, float(cruise_duration_s))
    descent_duration_s = max(60.0, descent_base_s + rng.uniform(-0.05, 0.05) * descent_base_s)
    landing_duration_s = max(15.0, 20.0 + rng.uniform(-3.0, 3.0))

    total_duration_s = (
        takeoff_duration_s
        + climb_duration_s
        + cruise_duration_s
        + descent_duration_s
        + landing_duration_s
    )
    return {
        "takeoff_duration_s": takeoff_duration_s,
        "climb_duration_s": climb_duration_s,
        "cruise_duration_s": cruise_duration_s,
        "descent_duration_s": descent_duration_s,
        "landing_duration_s": landing_duration_s,
        "total_duration_s": total_duration_s,
    }


def _compute_total_duration_s(
    *,
    takeoff_duration_s: float,
    altitude_delta_ft: float,
    climb_rate_fpm: float,
    descent_rate_fpm: float,
    cruise_duration_s: float,
    transition_duration_s: float,
) -> float:
    climb_duration_s = max(60.0, max(0.0, altitude_delta_ft) / float(climb_rate_fpm) * 60.0)
    descent_duration_s = max(60.0, max(0.0, altitude_delta_ft) / float(descent_rate_fpm) * 60.0)
    landing_duration_s = max(15.0, float(transition_duration_s))
    return (
        float(takeoff_duration_s)
        + climb_duration_s
        + max(0.0, float(cruise_duration_s))
        + descent_duration_s
        + landing_duration_s
    )


def build_mission_config(
    mission_type: str,
    *,
    mission_id: str | None = None,
    timestep_s: float = 10.0,
    random_seed: int = 42,
    initial_altitude_ft: float | None = None,
    target_altitude_ft: float | None = None,
    climb_rate_fpm: float | None = None,
    descent_rate_fpm: float | None = None,
    cruise_duration_s: float | None = None,
    takeoff_rpm: float | None = None,
    takeoff_throttle_pct: float | None = None,
    climb_rpm: float | None = None,
    climb_throttle_pct: float | None = None,
    cruise_rpm: float | None = None,
    cruise_throttle_pct: float | None = None,
    descent_rpm: float | None = None,
    descent_throttle_pct: float | None = None,
    ambient_temperature_offset_C: float | None = None,
    takeoff_duration_s: float | None = None,
    transition_duration_s: float | None = None,
) -> MissionConfig:
    if mission_type not in SUPPORTED_MISSION_TYPES:
        raise ValueError(f"Unsupported mission type: {mission_type}")

    template = MISSION_TEMPLATES[mission_type]
    rng = Random(int(random_seed))

    initial_altitude_ft = (
        float(initial_altitude_ft)
        if initial_altitude_ft is not None
        else _sample_range(rng, *template.initial_altitude_ft_range)
    )
    target_altitude_ft = (
        float(target_altitude_ft)
        if target_altitude_ft is not None
        else _sample_range(rng, *template.target_altitude_ft_range)
    )
    climb_rate_fpm = (
        float(climb_rate_fpm)
        if climb_rate_fpm is not None
        else _sample_range(rng, *template.climb_rate_fpm_range)
    )
    descent_rate_fpm = (
        float(descent_rate_fpm)
        if descent_rate_fpm is not None
        else _sample_range(rng, *template.descent_rate_fpm_range)
    )
    cruise_duration_s = (
        float(cruise_duration_s)
        if cruise_duration_s is not None
        else _sample_range(rng, *template.cruise_duration_s_range)
    )
    takeoff_duration_s = (
        float(takeoff_duration_s)
        if takeoff_duration_s is not None
        else _sample_range(rng, *template.takeoff_duration_s_range)
    )
    transition_duration_s = (
        float(transition_duration_s)
        if transition_duration_s is not None
        else _sample_range(rng, *template.transition_duration_s_range)
    )
    ambient_temperature_offset_C = (
        float(ambient_temperature_offset_C)
        if ambient_temperature_offset_C is not None
        else _sample_choice(rng, template.ambient_temperature_offset_C_options)
    )

    total_duration_s = _compute_total_duration_s(
        takeoff_duration_s=takeoff_duration_s,
        altitude_delta_ft=target_altitude_ft - initial_altitude_ft,
        climb_rate_fpm=climb_rate_fpm,
        descent_rate_fpm=descent_rate_fpm,
        cruise_duration_s=cruise_duration_s,
        transition_duration_s=transition_duration_s,
    )

    return MissionConfig(
        mission_id=mission_id or f"{template.mission_id_prefix}_{random_seed}",
        mission_type=mission_type,  # type: ignore[arg-type]
        timestep_s=timestep_s,
        total_duration_s=total_duration_s,
        initial_altitude_ft=initial_altitude_ft,
        target_altitude_ft=target_altitude_ft,
        climb_rate_fpm=climb_rate_fpm,
        descent_rate_fpm=descent_rate_fpm,
        cruise_duration_s=cruise_duration_s,
        takeoff_rpm=float(takeoff_rpm) if takeoff_rpm is not None else template.takeoff_rpm,
        takeoff_throttle_pct=float(takeoff_throttle_pct) if takeoff_throttle_pct is not None else template.takeoff_throttle_pct,
        climb_rpm=float(climb_rpm) if climb_rpm is not None else template.climb_rpm,
        climb_throttle_pct=float(climb_throttle_pct) if climb_throttle_pct is not None else template.climb_throttle_pct,
        cruise_rpm=float(cruise_rpm) if cruise_rpm is not None else template.cruise_rpm,
        cruise_throttle_pct=float(cruise_throttle_pct) if cruise_throttle_pct is not None else template.cruise_throttle_pct,
        descent_rpm=float(descent_rpm) if descent_rpm is not None else template.descent_rpm,
        descent_throttle_pct=float(descent_throttle_pct) if descent_throttle_pct is not None else template.descent_throttle_pct,
        ambient_temperature_offset_C=ambient_temperature_offset_C,
        random_seed=random_seed,
        takeoff_duration_s=takeoff_duration_s,
        transition_duration_s=transition_duration_s,
    )


def build_normal_mission_config(
    *,
    mission_id: str = "normal_mission_validation",
    timestep_s: float = 10.0,
    initial_altitude_ft: float = 0.0,
    target_altitude_ft: float = 10000.0,
    climb_rate_fpm: float = 1200.0,
    descent_rate_fpm: float = 1000.0,
    cruise_duration_s: float = 180.0,
    takeoff_rpm: float = 5800.0,
    takeoff_throttle_pct: float = 100.0,
    climb_rpm: float = 5500.0,
    climb_throttle_pct: float = 85.0,
    cruise_rpm: float = 4600.0,
    cruise_throttle_pct: float = 70.0,
    descent_rpm: float = 3000.0,
    descent_throttle_pct: float = 56.5,
    ambient_temperature_offset_C: float = 0.0,
    random_seed: int = 42,
) -> MissionConfig:
    durations = derive_normal_mission_durations(
        initial_altitude_ft=initial_altitude_ft,
        target_altitude_ft=target_altitude_ft,
        climb_rate_fpm=climb_rate_fpm,
        descent_rate_fpm=descent_rate_fpm,
        cruise_duration_s=cruise_duration_s,
        random_seed=random_seed,
    )
    return MissionConfig(
        mission_id=mission_id,
        mission_type=MISSION_TYPE_NORMAL,  # type: ignore[arg-type]
        timestep_s=timestep_s,
        total_duration_s=durations["total_duration_s"],
        initial_altitude_ft=initial_altitude_ft,
        target_altitude_ft=target_altitude_ft,
        climb_rate_fpm=climb_rate_fpm,
        descent_rate_fpm=descent_rate_fpm,
        cruise_duration_s=durations["cruise_duration_s"],
        takeoff_rpm=takeoff_rpm,
        takeoff_throttle_pct=takeoff_throttle_pct,
        climb_rpm=climb_rpm,
        climb_throttle_pct=climb_throttle_pct,
        cruise_rpm=cruise_rpm,
        cruise_throttle_pct=cruise_throttle_pct,
        descent_rpm=descent_rpm,
        descent_throttle_pct=descent_throttle_pct,
        ambient_temperature_offset_C=ambient_temperature_offset_C,
        random_seed=random_seed,
        takeoff_duration_s=durations["takeoff_duration_s"],
        transition_duration_s=durations["landing_duration_s"],
    )


def build_high_altitude_mission_config(**kwargs) -> MissionConfig:
    return build_mission_config(MISSION_TYPE_HIGH_ALTITUDE, **kwargs)


def build_endurance_mission_config(**kwargs) -> MissionConfig:
    return build_mission_config(MISSION_TYPE_ENDURANCE, **kwargs)


def build_hot_weather_mission_config(**kwargs) -> MissionConfig:
    return build_mission_config(MISSION_TYPE_HOT_WEATHER, **kwargs)


def build_high_power_mission_config(**kwargs) -> MissionConfig:
    return build_mission_config(MISSION_TYPE_HIGH_POWER, **kwargs)


def build_rapid_throttle_mission_config(**kwargs) -> MissionConfig:
    return build_mission_config(MISSION_TYPE_RAPID_THROTTLE, **kwargs)
