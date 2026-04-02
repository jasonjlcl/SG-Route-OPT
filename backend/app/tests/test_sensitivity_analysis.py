from app.services.sensitivity_analysis import _default_scenarios, _scale_service_time, _tighten_time_window


def test_tighten_time_window_trims_explicit_range():
    start, end = _tighten_time_window("09:00", "18:00")
    assert start == "09:30"
    assert end == "17:30"


def test_tighten_time_window_preserves_short_ranges():
    start, end = _tighten_time_window("09:00", "10:00")
    assert start == "09:00"
    assert end == "10:00"


def test_scale_service_time_rounds_up_for_non_zero_values():
    assert _scale_service_time(5, 1.2) == 6
    assert _scale_service_time(0, 1.2) == 0


def test_default_scenarios_cover_requested_factors():
    scenarios = _default_scenarios()
    scenario_ids = {item.scenario_id for item in scenarios}

    assert "BASE_CASE" in scenario_ids
    assert "FLEET_1" in scenario_ids
    assert "CAPACITY_30" in scenario_ids
    assert "WORKDAY_0900_1700" in scenario_ids
    assert "SERVICE_1_2X" in scenario_ids
    assert "TW_TIGHTER" in scenario_ids
