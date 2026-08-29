from __future__ import annotations

import pytest

from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput
from engine_model.stage5_mission_config import (
    MISSION_TYPE_ENDURANCE,
    MISSION_TYPE_HIGH_ALTITUDE,
    MISSION_TYPE_HIGH_POWER,
    MISSION_TYPE_HOT_WEATHER,
    MISSION_TYPE_NORMAL,
    MISSION_TYPE_RAPID_THROTTLE,
    build_endurance_mission_config,
    build_high_altitude_mission_config,
    build_high_power_mission_config,
    build_hot_weather_mission_config,
    build_normal_mission_config,
    build_rapid_throttle_mission_config,
)
from engine_model.stage5_mission_generator import MISSION_PHASES, NormalMissionGenerator


MISSION_CASES = [
    (MISSION_TYPE_NORMAL, build_normal_mission_config),
    (MISSION_TYPE_HIGH_ALTITUDE, build_high_altitude_mission_config),
    (MISSION_TYPE_ENDURANCE, build_endurance_mission_config),
    (MISSION_TYPE_HOT_WEATHER, build_hot_weather_mission_config),
    (MISSION_TYPE_HIGH_POWER, build_high_power_mission_config),
    (MISSION_TYPE_RAPID_THROTTLE, build_rapid_throttle_mission_config),
]


@pytest.mark.parametrize("mission_type,builder", MISSION_CASES)
def test_mission_starts_and_ends_correctly(mission_type, builder) -> None:
    mission_config = builder()
    generator = NormalMissionGenerator(mission_config)
    rows = generator.generate_rows()

    assert rows[0].phase == "TAKEOFF"
    assert rows[-1].phase == "IDLE/LANDING"
    assert rows[0].time_s == pytest.approx(0.0, abs=1e-12)
    assert rows[-1].time_s <= mission_config.total_duration_s + 1e-12
    assert rows[0].mission_id == mission_config.mission_id
    assert rows[0].mission_type == mission_type


@pytest.mark.parametrize("mission_type,builder", MISSION_CASES)
def test_phase_order_and_smooth_transitions(mission_type, builder) -> None:
    rows = NormalMissionGenerator(builder()).generate_rows()
    phase_index = {phase: idx for idx, phase in enumerate(MISSION_PHASES)}
    observed = [phase_index[row.phase] for row in rows]
    assert observed == sorted(observed)

    climb_rows = [row for row in rows if row.phase == "CLIMB"]
    cruise_rows = [row for row in rows if row.phase == "CRUISE"]
    descent_rows = [row for row in rows if row.phase == "DESCENT"]

    assert climb_rows[-1].altitude_ft > climb_rows[0].altitude_ft
    assert max(row.altitude_ft for row in cruise_rows) - min(row.altitude_ft for row in cruise_rows) <= 100.0
    assert descent_rows[-1].altitude_ft < descent_rows[0].altitude_ft

    max_rpm_step = max(abs(rows[idx + 1].rpm - rows[idx].rpm) for idx in range(len(rows) - 1))
    max_throttle_step = max(abs(rows[idx + 1].throttle_pct - rows[idx].throttle_pct) for idx in range(len(rows) - 1))
    assert max_rpm_step <= 1500.0
    assert max_throttle_step <= 35.0


@pytest.mark.parametrize("mission_type,builder", MISSION_CASES)
def test_no_nan_inf_or_invalid_negative_values(mission_type, builder) -> None:
    rows = NormalMissionGenerator(builder()).generate_rows()
    for row in rows:
        assert row.altitude_ft >= 0.0
        assert row.altitude_m >= 0.0
        assert row.rpm >= 0.0
        assert 56.5 <= row.throttle_pct <= 100.0
        assert row.ambient_pressure_hPa > 0.0
        assert row.power_kW is not None
        assert row.torque_Nm is not None
        assert row.fuelflow_kgh is not None
        assert row.p_plenum_bar is not None
        assert row.t_plenum_K is not None


def test_fixed_seed_is_deterministic() -> None:
    config = build_normal_mission_config(random_seed=101)
    rows_a = NormalMissionGenerator(config).generate_rows()
    rows_b = NormalMissionGenerator(config).generate_rows()
    assert [row.to_dict() for row in rows_a] == [row.to_dict() for row in rows_b]


@pytest.mark.parametrize("builder", [b for _, b in MISSION_CASES])
def test_different_seeds_produce_different_valid_output(builder) -> None:
    config_a = builder(random_seed=101)
    config_b = builder(random_seed=102)
    rows_a = NormalMissionGenerator(config_a).generate_rows()
    rows_b = NormalMissionGenerator(config_b).generate_rows()
    assert [row.to_dict() for row in rows_a] != [row.to_dict() for row in rows_b]


def test_stage3_case_2151_remains_unchanged() -> None:
    model = Stage13HybridEngineOutput()
    state = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)

    assert state.power_kW == pytest.approx(15.36454167, rel=0.0, abs=1e-8)
    assert state.torque_Nm == pytest.approx(48.90685510, rel=0.0, abs=1e-8)
    assert state.fuelflow_kgh == pytest.approx(6.02, rel=0.0, abs=1e-8)
    assert state.p_plenum_bar == pytest.approx(0.6256, rel=0.0, abs=1e-8)
    assert state.t_plenum_K == pytest.approx(289.85, rel=0.0, abs=1e-8)


def test_normal_mission_uses_fixed_one_second_grid() -> None:
    config = build_normal_mission_config(timestep_s=1.0, random_seed=42)
    rows = NormalMissionGenerator(config).generate_rows()

    assert rows[0].time_s == pytest.approx(0.0, abs=1e-12)
    assert rows[-1].time_s <= config.total_duration_s + 1e-12

    deltas = [round(rows[idx + 1].time_s - rows[idx].time_s, 12) for idx in range(len(rows) - 1)]
    assert deltas
    assert set(deltas) == {1.0}
    assert all(float(row.time_s).is_integer() for row in rows)

    phases = {row.phase for row in rows}
    assert "TAKEOFF" in phases
    assert "CLIMB" in phases
    assert "CRUISE" in phases
    assert "DESCENT" in phases
    assert "IDLE/LANDING" in phases
