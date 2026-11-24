from pathlib import Path

import pytest

from app.brackets.loader import load_bracket
from app.brackets.runtime import BracketRuntime, ChampionshipPhase
from app.brackets.scheduler import BoardScheduler, BoardSchedulerError

DATA_DIR = Path(__file__).parents[1] / "data"


def runtime_for(team_count: int = 4) -> BracketRuntime:
    definition = load_bracket(DATA_DIR / f"{team_count}teamD.json")
    entrants = {f"T{seed}": f"Team {seed}" for seed in range(1, team_count + 1)}
    return BracketRuntime(definition, entrants)


def test_all_four_boards_are_always_available_and_matches_are_not_auto_assigned():
    runtime = runtime_for()
    scheduler = BoardScheduler()

    assert scheduler.enabled_boards == (1, 2, 3, 4)
    assert scheduler.assignments == ()
    assert len(scheduler.ready_matches(runtime)) == 2
    assert scheduler.start_available(runtime) == ()
    assert scheduler.assignments == ()


def test_two_ready_matches_recommend_spread_boards_but_do_not_assign():
    runtime = runtime_for()
    scheduler = BoardScheduler()

    assert scheduler.recommended_boards(runtime) == (1, 3)
    assert scheduler.assignments == ()

    scheduler.assign(3, "G2", runtime)
    assert scheduler.recommended_boards(runtime) == (1,)
    assert [(item.board_id, item.match.match_id) for item in scheduler.assignments] == [(3, "G2")]


def test_operator_can_assign_any_ready_match_to_any_free_board():
    runtime = runtime_for()
    scheduler = BoardScheduler()

    second = scheduler.assign(4, "G2", runtime)
    first = scheduler.assign(2, "G1", runtime)

    assert second.board_id == 4
    assert first.board_id == 2
    assert scheduler.free_boards == (1, 3)
    with pytest.raises(BoardSchedulerError, match="already has an active match"):
        scheduler.assign(2, "G3", runtime)
    with pytest.raises(BoardSchedulerError, match="not ready"):
        scheduler.assign(1, "G3", runtime)


def test_completed_match_frees_board_without_auto_assigning_next_ready_match():
    runtime = runtime_for()
    scheduler = BoardScheduler()
    scheduler.assign(1, "G1", runtime)
    scheduler.assign(3, "G2", runtime)

    scheduler.complete(1, "Team 1", runtime)
    scheduler.complete(3, "Team 2", runtime)

    assert scheduler.assignments == ()
    assert [match.match_id for match in scheduler.ready_matches(runtime)] == ["G3", "G4"]
    assert scheduler.recommended_boards(runtime) == (1, 3)
    assert scheduler.start_available(runtime) == ()


def test_championship_reset_retains_same_board_and_logical_match():
    runtime = runtime_for()
    for match_id, winner in [
        ("G1", "Team 1"),
        ("G2", "Team 2"),
        ("G3", "Team 1"),
        ("G4", "Team 4"),
        ("G5", "Team 4"),
    ]:
        runtime.record_winner(match_id, winner)

    scheduler = BoardScheduler()
    first = scheduler.assign(3, "CHAMPIONSHIP", runtime)
    assert first.match.source_game_id == "GF"

    reset = scheduler.complete(3, "Team 4", runtime)

    assert reset is not None
    assert reset.board_id == 3
    assert reset.match.match_id == "CHAMPIONSHIP"
    assert reset.match.source_game_id == "GGF"
    assert reset.match.phase == ChampionshipPhase.RESET
    scheduler.complete(3, "Team 1", runtime)
    assert scheduler.assignments == ()


def test_unassign_releases_board_and_returns_match_to_ready_queue():
    runtime = runtime_for()
    scheduler = BoardScheduler()
    assignment = scheduler.assign(2, "G1", runtime)

    released = scheduler.unassign(2)

    assert released == assignment
    assert scheduler.free_boards == (1, 2, 3, 4)
    assert [match.match_id for match in scheduler.ready_matches(runtime)] == ["G1", "G2"]
    with pytest.raises(BoardSchedulerError, match="no assigned match"):
        scheduler.unassign(2)


def test_board_ids_are_validated():
    scheduler = BoardScheduler()
    with pytest.raises(BoardSchedulerError, match="integer from 1 to 4"):
        scheduler.assign(5, "G1", runtime_for())
