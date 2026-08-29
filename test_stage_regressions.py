from __future__ import annotations

import pytest

from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput
from engine_model.stage4_health_parameters import (
    GENERATOR_SWITCH_HOLD_TIME_S,
    GENERATOR_SWITCH_THRESHOLD_RPM,
    generator_switch_state,
    update_generator_switch_timer,
)


def _simulate_switch_sequence(steps: list[tuple[float, float]]) -> tuple[float, object]:
    above_threshold_time_s = 0.0
    last_rpm = 0.0
    for rpm, dt_s in steps:
        above_threshold_time_s = update_generator_switch_timer(above_threshold_time_s, rpm, dt_s)
        last_rpm = rpm
    return above_threshold_time_s, generator_switch_state(last_rpm, time_above_threshold_s=above_threshold_time_s)


def test_canonical_ambient_resolution_and_explicit_temperature() -> None:
    model = Stage13HybridEngineOutput()

    canonical = model.get_engine_state(5800.0, 100.0, 22999.0)
    explicit = model.get_engine_state(5800.0, 100.0, 22999.0, -1.0)

    assert canonical.ambient_source == "isa_surrogate"
    assert explicit.ambient_source == "explicit_input"
    assert canonical.power_kW != 0.0
    assert canonical.t_plenum_K != 0.0


def test_case_2151_regression() -> None:
    model = Stage13HybridEngineOutput()
    state = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)

    assert state.power_kW == pytest.approx(15.36454167, rel=0.0, abs=1e-8)
    assert state.torque_Nm == pytest.approx(48.90685510, rel=0.0, abs=1e-8)
    assert state.fuelflow_kgh == pytest.approx(6.02, rel=0.0, abs=1e-8)
    assert state.p_plenum_bar == pytest.approx(0.6256, rel=0.0, abs=1e-8)
    assert state.t_plenum_K == pytest.approx(289.85, rel=0.0, abs=1e-8)


@pytest.mark.parametrize(
    "steps, expected_latched",
    [
        ([(2390.0, 20.0)], False),
        ([(2500.0, 7.9)], False),
        ([(2500.0, 8.0)], True),
        ([(2500.0, 5.0), (2300.0, 1.0), (2500.0, 3.0)], False),
        ([(2500.0, 8.1)], True),
        ([(2400.0, 8.0)], True),
    ],
)
def test_generator_switch_requires_continuous_above_threshold_time(
    steps: list[tuple[float, float]],
    expected_latched: bool,
) -> None:
    above_threshold_time_s, state = _simulate_switch_sequence(steps)

    assert state.threshold_rpm == pytest.approx(GENERATOR_SWITCH_THRESHOLD_RPM, rel=0.0, abs=1e-12)
    assert state.hold_time_s == pytest.approx(GENERATOR_SWITCH_HOLD_TIME_S, rel=0.0, abs=1e-12)
    assert above_threshold_time_s >= 0.0
    assert state.latched is expected_latched
