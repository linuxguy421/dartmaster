from pathlib import Path

import pytest

from app.brackets.loader import load_bracket
from app.brackets.runtime import BracketRuntime, ChampionshipPhase
from app.brackets.scheduler import BoardScheduler, SchedulerMode
from app.state.store import TournamentStateStore, TournamentStoreError

DATA_DIR = Path(__file__).parents[1] / "data"


def make_runtime() -> BracketRuntime:
    definition = load_bracket(DATA_DIR / "4teamD.json")
    entrants = {
        "T1": "Team One",
        "T2": "Team Two",
        "T3": "Team Three",
        "T4": "Team Four",
    }
    return BracketRuntime(definition, entrants)


def test_save_and_restore_preserves_results_board_assignments_and_manual_mode(tmp_path):
    definition = load_bracket(DATA_DIR / "4teamD.json")
    runtime = make_runtime()
    scheduler = BoardScheduler()
    scheduler.enable_board(2)
    scheduler.enable_board(4)
    scheduler.start_available(runtime)

    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    store.save(
        "league-night-2026-11-17",
        "data/4teamD.json",
        runtime,
        scheduler,
        event_type="tournament_started",
        event_payload={"team_count": 4},
    )

    restored_runtime, restored_scheduler, bracket_file, _ = store.restore(
        "league-night-2026-11-17", definition
    )

    assert bracket_file == "data/4teamD.json"
    assert restored_runtime.entrants == runtime.entrants
    assert restored_runtime.results == {}
    assert restored_scheduler.mode == SchedulerMode.MANUAL
    assert restored_scheduler.enabled_boards == (2, 4)
    assert [
        (item.board_id, item.match.match_id) for item in restored_scheduler.assignments
    ] == [(2, "G1"), (4, "G2")]
    assert store.events("league-night-2026-11-17")[0]["event_type"] == "tournament_started"


def test_restore_replays_results_and_preserves_championship_reset_board(tmp_path):
    definition = load_bracket(DATA_DIR / "4teamD.json")
    runtime = make_runtime()
    runtime.record_winner("G1", "Team One")
    runtime.record_winner("G2", "Team Two")
    runtime.record_winner("G3", "Team One")
    runtime.record_winner("G4", "Team Four")
    runtime.record_winner("G5", "Team Four")

    scheduler = BoardScheduler(mode=SchedulerMode.AUTO)
    championship = scheduler.start_available(runtime)[0]
    assert championship.match.match_id == "CHAMPIONSHIP"
    scheduler.complete(championship.board_id, "Team Four", runtime)

    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    store.save(
        "championship-night",
        "data/4teamD.json",
        runtime,
        scheduler,
        event_type="championship_reset_started",
    )

    restored_runtime, restored_scheduler, _, _ = store.restore(
        "championship-night", definition
    )

    assert restored_runtime.championship_phase == ChampionshipPhase.RESET
    assert restored_runtime.results["GF"].winner == "Team Four"
    assert restored_scheduler.mode == SchedulerMode.AUTO
    assert len(restored_scheduler.assignments) == 1
    assignment = restored_scheduler.assignments[0]
    assert assignment.board_id == championship.board_id
    assert assignment.match.match_id == "CHAMPIONSHIP"
    assert assignment.match.source_game_id == "GGF"
    assert assignment.match.phase == ChampionshipPhase.RESET


def test_unknown_tournament_is_reported(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")

    with pytest.raises(TournamentStoreError, match="Unknown tournament"):
        store.load("missing")


def test_each_save_appends_an_event_atomically(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    runtime = make_runtime()
    scheduler = BoardScheduler()

    store.save("event-test", "data/4teamD.json", runtime, scheduler, event_type="created")
    runtime.record_winner("G1", "Team One")
    store.save(
        "event-test",
        "data/4teamD.json",
        runtime,
        scheduler,
        event_type="match_completed",
        event_payload={"match_id": "G1", "winner": "Team One"},
    )

    events = store.events("event-test")
    assert [event["event_type"] for event in events] == ["created", "match_completed"]
    assert events[1]["payload"] == {"match_id": "G1", "winner": "Team One"}
