"""
test_simulator_skeleton.py — Week 2 sanity tests.

These confirm the skeleton's CURRENT state: it instantiates correctly,
and unimplemented methods raise NotImplementedError (not silently
return fake data). When Week 4 implements the real logic, these
NotImplementedError assertions get replaced with real behavior tests —
this file's job right now is just to prove the contract is locked in,
not to test logic that doesn't exist yet.

Path setup is handled centrally by conftest.py at the repo root.
"""
import pytest
from simulator.telemetry_simulator import TelemetrySimulator, Scenario


def test_simulator_instantiates():
    sim = TelemetrySimulator(device_id="DL1ZAA1234", scenario=Scenario.HIGHWAY, seed=42)
    assert sim.device_id == "DL1ZAA1234"
    assert sim.scenario == Scenario.HIGHWAY


def test_all_three_scenarios_exist():
    assert Scenario.HIGHWAY.value == "highway"
    assert Scenario.CITY.value == "city"
    assert Scenario.DEGRADED_SIGNAL.value == "degraded_signal"


def test_generate_route_not_yet_implemented():
    # Week 2 expectation. This test should be REPLACED (not just
    # deleted) in Week 4 with a real assertion about route output.
    sim = TelemetrySimulator(device_id="X", scenario=Scenario.CITY)
    with pytest.raises(NotImplementedError):
        sim.generate_route(start_lat=12.9716, start_lon=77.5946, duration_minutes=10)
