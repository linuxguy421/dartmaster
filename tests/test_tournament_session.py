from pathlib import Path

from app.brackets.loader import load_bracket
from app.brackets.runtime import ChampionshipPhase
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


def test_new_session_keeps_all_boards_available_and_persists_operator_assignment(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "friday-night",
        "data/4teamD.json",
        definition(),
        entrants(),
        store,
    )

    assert session.scheduler.enabled_boards == (1, 2, 3, 4)
    assert session.scheduler.assignments == ()

    session.assign_match(3, "G1")
    assert [(item.board_id, item.match.match_id) for item in session.scheduler.assignments] == [
        (3, "G1")
    ]

    restored = TournamentSession.restore("friday-night", definition(), store)
    assert restored.scheduler.enabled_boards == (1, 2, 3, 4)
    assert restored.scheduler.assignments[0].match.match_id == "G1"


def test_session_completion_does_not_auto_assign_next_ready_match(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "operator-night",
        "data/4teamD.json",
        definition(),
        entrants(),
        store,
    )
    session.assign_match(1, "G1")
    session.assign_match(3, "G2")

    session.complete_match(1, "Team One")
    session.complete_match(3, "Team Two")

    assert session.scheduler.assignments == ()
    assert [match.match_id for match in session.scheduler.ready_matches(session.runtime)] == ["G3", "G4"]
    restored = TournamentSession.restore("operator-night", definition(), store)
    assert restored.runtime.results["G1"].winner == "Team One"
    assert restored.runtime.results["G2"].winner == "Team Two"
    assert restored.scheduler.assignments == ()


def test_session_keeps_championship_reset_on_original_board_after_restore(tmp_path):
    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    session = TournamentSession.create(
        "finals-night",
        "data/4teamD.json",
        definition(),
        entrants(),
        store,
    )
    for match_id, winner in [
        ("G1", "Team One"),
        ("G2", "Team Two"),
        ("G3", "Team One"),
        ("G4", "Team Four"),
        ("G5", "Team Four"),
    ]:
        session.assign_match(1, match_id)
        session.complete_match(1, winner)

    session.assign_match(3, "CHAMPIONSHIP")
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
    roster.register_player("p5", "Jordan", Gender.MALE)
    roster.register_player("p6", "Riley", Gender.FEMALE)
    roster.register_player("p7", "Cameron", Gender.MALE)
    roster.register_player("p8", "Avery", Gender.FEMALE)
    roster.create_team("a", "Team One", "p1", "p2")
    roster.create_team("b", "Team Two", "p3", "p4")
    roster.create_team("c", "Team Three", "p5", "p6")
    roster.create_team("d", "Team Four", "p7", "p8")
    roster.assign_seed("T1", "a")
    roster.assign_seed("T2", "b")
    roster.assign_seed("T3", "c")
    roster.assign_seed("T4", "d")

    store = TournamentStateStore(tmp_path / "dartmaster.sqlite3")
    TournamentSession.create(
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
