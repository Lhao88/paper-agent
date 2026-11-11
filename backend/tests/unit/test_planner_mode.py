from app.worker.execute import frozen_planner_mode


def test_matching_snapshots_select_coverage_without_process_config() -> None:
    mode = frozen_planner_mode(
        {"planner_mode": "coverage"},
        {"planner_mode": "coverage"},
    )
    assert mode == "coverage"


def test_matching_legacy_snapshots_ignore_a_later_coverage_process_value() -> None:
    mode = frozen_planner_mode(
        {"planner_mode": "legacy", "process_planner_mode": "coverage"},
        {"planner_mode": "legacy"},
    )
    assert mode == "legacy"


def test_disagreement_does_not_invent_coverage_from_process_config() -> None:
    assert (
        frozen_planner_mode(
            {"planner_mode": "coverage"},
            {"planner_mode": "legacy"},
        )
        == "legacy"
    )


def test_missing_snapshot_mode_stays_on_development_default() -> None:
    assert frozen_planner_mode({}, {}) == "legacy"


def test_one_frozen_snapshot_is_used_when_the_other_has_no_mode() -> None:
    assert frozen_planner_mode({}, {"planner_mode": "coverage"}) == "coverage"
    assert frozen_planner_mode({"planner_mode": "legacy"}, {}) == "legacy"
