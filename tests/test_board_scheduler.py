from pathlib import Path

import pytest

from app.brackets.loader import load_bracket
from app.brackets.runtime import BracketRuntime, ChampionshipPhase
from app.brackets.scheduler import (
    BoardScheduler,
    BoardSchedulerError,
    SchedulerMode,
)

DATA_DIR = Path(__file__).parents[1] / "data"


def runtime_for(team_count: int = 4) -> BracketRuntime:
    definition = load_bracket(DATA_DIR / f"{team_count}teamD.json")
    entrants = {
        f"T{seed}": f"Team {seed}" for seed in range(1, team_count + 1)
    }
    return BracketRuntime(definition, entrants)


def test_scheduler_defaults_to_manual_with_no_boards_enabled():
    scheduler = BoardScheduler()

    assert scheduler.mode == SchedulerMode.MANUAL
    assert scheduler.enabled_boards == ()
    assert scheduler.assignments == ()


def test_manual_mode_only_uses_operator_enabled_boards():
    runtime = runtime_for()
    scheduler = BoardScheduler()
    scheduler.enable_board(2)
    scheduler.enable_board(4)

    assignments = scheduler.start_available(runtime)

    assert [(item.board_id, item.match.match_id) for item in assignments] == [
        (2, "G1"),
        (4, "G2"),
    ]


def test_auto_mode_uses_all_boards_but_only_assigns_ready_matches():
    runtime = runtime_for(8)
    scheduler = BoardScheduler(mode=SchedulerMode.AUTO)

    assignments = scheduler.start_available(runtime)

    assert scheduler.enabled_boards == (1, 2, 3, 4)
    assert len(assignments) == 4
    assert [item.board_id for item in assignments] == [1, 2, 3, 4]
    assert len({item.match.match_id for item in assignments}) == 4


def test_manual_scheduler_can_fill_newly_ready_match_on_freed_board():
    runtime = runtime_for()
    scheduler = BoardScheduler()
    scheduler.enable_board(1)
    scheduler.enable_board(2)
    scheduler.start_available(runtime)

    scheduler.complete(1, "Team 1", runtime)
    scheduler.complete(2, "Team 2", runtime)
    scheduler.disable_board(2)
    assignments = scheduler.start_available(runtime)

    assert [(item.board_id, item.match.match_id) for item in assignments] == [
        (1, "G3"),
    ]


def test_championship_reset_retains_same_board_and_logical_match():
    runtime = runtime_for()
    runtime.record_winner("G1", "Team 1")
    runtime.record_winner("G2", "Team 2")
    runtime.record_winner("G3", "Team 1")
    runtime.record_winner("G4", "Team 4")
    runtime.record_winner("G5", "Team 4")

    scheduler = BoardScheduler()
    scheduler.enable_board(3)
    first = scheduler.start_available(runtime)[0]
    assert first.match.match_id == "CHAMPIONSHIP"
    assert first.match.source_game_id == "GF"

    reset = scheduler.complete(3, "Team 4", runtime)

    assert reset is not None
    assert reset.board_id == 3
    assert reset.match.match_id == "CHAMPIONSHIP"
    assert reset.match.source_game_id == "GGF"
    assert reset.match.phase == ChampionshipPhase.RESET
    assert scheduler.start_available(runtime) == (reset,)

    scheduler.complete(3, "Team 1", runtime)
    assert scheduler.assignments == ()



