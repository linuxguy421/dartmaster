from pathlib import Path

import pytest

from app.brackets.loader import load_bracket
from app.registration import Gender, RegistrationError, TournamentRoster

DATA_DIR = Path(__file__).parents[1] / "data"


def registered_roster() -> TournamentRoster:
    roster = TournamentRoster()
    roster.register_player("p1", "Alex", Gender.MALE)
    roster.register_player("p2", "Jamie", Gender.FEMALE)
    roster.register_player("p3", "Morgan", Gender.MALE)
    roster.register_player("p4", "Taylor", Gender.FEMALE)
    roster.create_team("team-a", "Team A", "p1", "p2")
    roster.create_team("team-b", "Team B", "p3", "p4")
    roster.register_player("p5", "Jordan", Gender.MALE)
    roster.register_player("p6", "Riley", Gender.FEMALE)
    roster.register_player("p7", "Cameron", Gender.MALE)
    roster.register_player("p8", "Avery", Gender.FEMALE)
    roster.create_team("team-c", "Team C", "p5", "p6")
    roster.create_team("team-d", "Team D", "p7", "p8")
    return roster


def test_registers_players_and_creates_two_player_team():
    roster = registered_roster()
    team = roster.teams["team-a"]

    assert team.player_one_id == "p1"
    assert team.player_two_id == "p2"
    assert roster.players[team.player_one_id].gender == Gender.MALE
    assert roster.players[team.player_two_id].gender == Gender.FEMALE


@pytest.mark.parametrize(
    ("first_id", "second_id"),
    [("p1", "p1"), ("missing", "p2"), ("p1", "missing")],
)
def test_rejects_invalid_team_members(first_id, second_id):
    roster = registered_roster()
    with pytest.raises(RegistrationError):
        roster.create_team("bad", "Bad Team", first_id, second_id)


@pytest.mark.parametrize(
    ("first_gender", "second_gender"),
    [
        (Gender.MALE, Gender.MALE),
        (Gender.FEMALE, Gender.FEMALE),
    ],
)
def test_allows_same_gender_teams(first_gender, second_gender):
    roster = TournamentRoster()
    roster.register_player("first", "First Player", first_gender)
    roster.register_player("second", "Second Player", second_gender)

    team = roster.create_team("same-sex", "Same Gender Team", "first", "second")

    assert team.player_one_id == "first"
    assert team.player_two_id == "second"
    assert roster.players[team.player_one_id].gender == first_gender
    assert roster.players[team.player_two_id].gender == second_gender


def test_player_cannot_be_reused_across_teams():
    roster = registered_roster()
    roster.register_player("p9", "Casey", Gender.FEMALE)

    with pytest.raises(RegistrationError, match="more than one team"):
        roster.create_team("team-e", "Team E", "p1", "p9")


def test_rejects_duplicate_player_and_team_names():
    roster = registered_roster()
    with pytest.raises(RegistrationError, match="Player ID already exists"):
        roster.register_player("p1", "Another Alex", Gender.MALE)
    with pytest.raises(RegistrationError, match="Team name already exists"):
        roster.create_team("team-e", "team a", "p1", "p4")


def test_assigns_unique_teams_to_exact_bracket_seeds():
    roster = registered_roster()
    roster.assign_seed("T1", "team-a")
    roster.assign_seed("T2", "team-b")
    roster.assign_seed("T3", "team-c")
    roster.assign_seed("T4", "team-d")
    definition = load_bracket(DATA_DIR / "4teamD.json")

    assert roster.runtime_entrants(definition) == {
        "T1": "Team A",
        "T2": "Team B",
        "T3": "Team C",
        "T4": "Team D",
    }
    roster.validate_for_bracket(definition)


def test_rejects_duplicate_seed_or_team_assignment():
    roster = registered_roster()
    roster.assign_seed("T1", "team-a")
    with pytest.raises(RegistrationError, match="already assigned"):
        roster.assign_seed("T1", "team-b")
    with pytest.raises(RegistrationError, match="already assigned"):
        roster.assign_seed("T2", "team-a")


def test_roster_round_trips_and_revalidates_constraints():
    roster = registered_roster()
    roster.assign_seed("T1", "team-a")
    roster.assign_seed("T2", "team-b")

    restored = TournamentRoster.from_dict(roster.to_dict())

    assert restored.to_dict() == roster.to_dict()
    assert restored.team_for_seed("T1").name == "Team A"


def test_loads_legacy_mixed_doubles_snapshot():
    legacy = {
        "players": [
            {"player_id": "m", "display_name": "Male", "gender": "male"},
            {"player_id": "f", "display_name": "Female", "gender": "female"},
        ],
        "teams": [
            {
                "team_id": "team",
                "name": "Legacy Team",
                "male_player_id": "m",
                "female_player_id": "f",
            }
        ],
        "seed_assignments": {"T1": "team"},
    }

    restored = TournamentRoster.from_dict(legacy)

    assert restored.teams["team"].player_one_id == "m"
    assert restored.teams["team"].player_two_id == "f"
