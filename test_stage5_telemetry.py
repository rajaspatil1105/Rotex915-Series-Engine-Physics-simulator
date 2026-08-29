from __future__ import annotations

import pytest

from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput, isa_temp_c
from engine_model.stage4_health_parameters import generator_switch_state, update_generator_switch_timer
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
from engine_model.stage5_mission_generator import NormalMissionGenerator
from engine_model.stage5_simulation_pipeline import TELEMETRY_FIELDNAMES, run_mission


MISSION_CASES = [
    (MISSION_TYPE_NORMAL, build_normal_mission_config),
    (MISSION_TYPE_HIGH_ALTITUDE, build_high_altitude_mission_config),
    (MISSION_TYPE_ENDURANCE, build_endurance_mission_config),
    (MISSION_TYPE_HOT_WEATHER, build_hot_weather_mission_config),
    (MISSION_TYPE_HIGH_POWER, build_high_power_mission_config),
    (MISSION_TYPE_RAPID_THROTTLE, build_rapid_throttle_mission_config),
]


@pytest.mark.parametrize("mission_type,builder", MISSION_CASES)
def test_complete_telemetry_schema_and_alignment(mission_type, builder) -> None:
    config = builder()
    telemetry_rows = run_mission(config)
    mission_rows = NormalMissionGenerator(config).generate_rows()

    assert telemetry_rows
    assert list(telemetry_rows[0].to_dict().keys()) == TELEMETRY_FIELDNAMES
    assert len(telemetry_rows) == len(mission_rows)
    assert telemetry_rows[0].mission_type == mission_type
    assert telemetry_rows[0].time_s == pytest.approx(0.0, abs=1e-12)
    assert telemetry_rows[-1].time_s <= config.total_duration_s + 1e-12
    assert telemetry_rows[0].stage3_ambient_source == "explicit_input"
    assert telemetry_rows[0].ambient_source == "python_generated_isa_plus_offset"
    assert telemetry_rows[0].stage3_values == "csv_authoritative"
    assert telemetry_rows[0].mission_generated_values == "python_mission_generator"

    if config.timestep_s == pytest.approx(1.0, abs=1e-12):
        assert telemetry_rows[0].time_s == pytest.approx(0.0, abs=1e-12)
        assert all(
            telemetry_rows[idx + 1].time_s - telemetry_rows[idx].time_s == pytest.approx(1.0, abs=1e-12)
            for idx in range(len(telemetry_rows) - 1)
        )
        assert all(float(row.time_s).is_integer() for row in telemetry_rows)

    for telemetry_row, mission_row in zip(telemetry_rows, mission_rows):
        assert telemetry_row.rpm == pytest.approx(mission_row.rpm, rel=0.0, abs=1e-9)
        assert telemetry_row.throttle_pct == pytest.approx(mission_row.throttle_pct, rel=0.0, abs=1e-9)
        assert telemetry_row.altitude_ft == pytest.approx(mission_row.altitude_ft, rel=0.0, abs=1e-9)
        assert telemetry_row.ambient_temperature_C == pytest.approx(mission_row.ambient_temperature_C, rel=0.0, abs=1e-9)

    model = Stage13HybridEngineOutput()
    previous_timer = 0.0
    previous_time = 0.0
    for row in telemetry_rows:
        dt_s = 0.0 if row.time_s == 0.0 else row.time_s - previous_time
        previous_timer = update_generator_switch_timer(previous_timer, row.rpm, dt_s)
        expected_switch = generator_switch_state(row.rpm, time_above_threshold_s=previous_timer)
        assert row.generator_time_above_threshold_s == pytest.approx(previous_timer, abs=1e-9)
        assert row.generator_switch_ready == expected_switch.ready
        assert row.generator_switch_latched == expected_switch.latched
        assert row.stage4_production_source == "calibrated_csv"
        assert row.engine_state_valid
        assert not row.outside_calibrated_envelope
        assert not row.extrapolation_used
        assert row.health_state_valid

        engine_state = model.get_engine_state(row.rpm, row.throttle_pct, row.altitude_ft, row.ambient_temperature_C)
        assert row.power_kW == pytest.approx(engine_state.power_kW, rel=0.0, abs=1e-8)
        assert row.torque_Nm == pytest.approx(engine_state.torque_Nm, rel=0.0, abs=1e-8)
        assert row.fuelflow_kgh == pytest.approx(engine_state.fuelflow_kgh, rel=0.0, abs=1e-8)
        assert row.p_plenum_bar == pytest.approx(engine_state.p_plenum_bar, rel=0.0, abs=1e-8)
        assert row.t_plenum_K == pytest.approx(engine_state.t_plenum_K, rel=0.0, abs=1e-8)

        if mission_type == MISSION_TYPE_HOT_WEATHER:
            offset = row.ambient_temperature_C - isa_temp_c(row.altitude_ft)
            assert any(abs(offset - candidate) <= 1e-9 for candidate in (15.0, 30.0))

        previous_time = row.time_s


def test_generator_timer_reset_behavior() -> None:
    timer = 0.0
    timer = update_generator_switch_timer(timer, 2500.0, 4.0)
    assert timer == pytest.approx(4.0, abs=1e-12)
    timer = update_generator_switch_timer(timer, 2300.0, 1.0)
    assert timer == pytest.approx(0.0, abs=1e-12)
    timer = update_generator_switch_timer(timer, 2500.0, 8.0)
    assert timer == pytest.approx(8.0, abs=1e-12)
    assert generator_switch_state(2500.0, time_above_threshold_s=timer).latched
