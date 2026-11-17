from pathlib import Path

from app.brackets.loader import load_bracket
from app.brackets.runtime import ChampionshipPhase
from app.brackets.scheduler import SchedulerMode
from app.state.session import TournamentSession
from app.state.store import TournamentStateStore

DATA_DIR = Path(__file__).parents[1] / "data"


def definition():
    return load_bracket(DATA_DIR / "4teamD.json")


def entrants():
    return {
        "T1": "Team One",
        "T2": "Team Two",
        "T3": "Team Three",
        "T4": "Team Four",
    }


def test_new_session_defaults_to_manual_and_persists_operator_board_selection(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "friday-night",
        "data/4teamD.json",
        definition(),
        entrants(),
        store,
    )

    assert session.scheduler.mode == SchedulerMode.MANUAL
    assert session.scheduler.enabled_boards == ()
    assert session.scheduler.assignments == ()

    session.enable_board(3)
    assert [(item.board_id, item.match.match_id) for item in session.scheduler.assignments] == [
        (3, "G1")
    ]

    restored = TournamentSession.restore("friday-night", definition(), store)
    assert restored.scheduler.enabled_boards == (3,)
    assert restored.scheduler.assignments[0].match.match_id == "G1"


def test_session_persists_match_results_and_refills_boards_in_auto_mode(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "auto-night",
        "data/4teamD.json",
        definition(),
        entrants(),
        store,
        mode=SchedulerMode.AUTO,
    )
    assert [item.match.match_id for item in session.scheduler.assignments] == ["G1", "G2"]

    session.complete_match(1, "Team One")
    assert session.runtime.results["G1"].winner == "Team One"

    session.complete_match(2, "Team Two")
    assert session.scheduler.assignments[0].match.match_id == "G3"

    restored = TournamentSession.restore("auto-night", definition(), store)
    assert restored.runtime.results["G1"].winner == "Team One"
    assert restored.runtime.results["G2"].winner == "Team Two"
    assert restored.scheduler.assignments[0].match.match_id == "G3"
    assert [event["event_type"] for event in store.events("auto-night")][-2:] == [
        "match_completed",
        "match_completed",
    ]


def test_session_keeps_championship_reset_on_original_board_after_restore(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "finals-night",
        "data/4teamD.json",
        definition(),
        entrants(),
        store,
        mode=SchedulerMode.AUTO,
    )
    for match_id, winner in [
        ("G1", "Team One"),
        ("G2", "Team Two"),
        ("G3", "Team One"),
        ("G4", "Team Four"),
        ("G5", "Team Four"),
    ]:
        assignment = next(
            item for item in session.scheduler.assignments
            if item.match.match_id == match_id
        )
        session.complete_match(assignment.board_id, winner)

    championship = session.scheduler.assignments[0]
    board_id = championship.board_id
    session.complete_match(board_id, "Team Four")
    restored = TournamentSession.restore("finals-night", definition(), store)

    assert restored.runtime.championship_phase == ChampionshipPhase.RESET
    assert len(restored.scheduler.assignments) == 1
    assert restored.scheduler.assignments[0].board_id == board_id
    assert restored.scheduler.assignments[0].match.source_game_id == "GGF"



def test_session_persists_and_restores_player_team_roster(tmp_path):
    from app.registration import Gender, TournamentRoster

    roster = TournamentRoster()
    roster.register_player("p1", "Alex", Gender.MALE)
    roster.register_player("p2", "Jamie", Gender.FEMALE)
    roster.register_player("p3", "Morgan", Gender.MALE)
    roster.register_player("p4", "Taylor", Gender.FEMALE)
    roster.create_team("a", "Team One", "p1", "p2")
    roster.create_team("b", "Team Two", "p3", "p4")
    roster.assign_seed("T1", "a")
    roster.assign_seed("T2", "b")

    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "registered-night",
        "data/4teamD.json",
        definition(),
        roster.runtime_entrants(definition()),
        store,
        roster=roster,
    )

    restored = TournamentSession.restore("registered-night", definition(), store)
    assert restored.roster is not None
    assert restored.roster.to_dict() == roster.to_dict()
