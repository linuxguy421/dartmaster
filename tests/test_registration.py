import pytest

from app.brackets.loader import load_bracket
from app.registration import Gender, RegistrationError, TournamentRoster

from pathlib import Path

DATA_DIR = Path(__file__).parents[1] / "data"


def registered_roster() -> TournamentRoster:
    roster = TournamentRoster()
    roster.register_player("p1", "Alex", Gender.MALE)
    roster.register_player("p2", "Jamie", Gender.FEMALE)
    roster.register_player("p3", "Morgan", Gender.MALE)
    roster.register_player("p4", "Taylor", Gender.FEMALE)
    roster.create_team("team-a", "Team A", "p1", "p2")
    roster.create_team("team-b", "Team B", "p3", "p4")
    return roster


def test_registers_players_and_creates_one_male_one_female_team():
    roster = registered_roster()
    team = roster.teams["team-a"]

    assert roster.players[team.male_player_id].gender == Gender.MALE
    assert roster.players[team.female_player_id].gender == Gender.FEMALE


@pytest.mark.parametrize(
    ("male_id", "female_id"),
    [("p2", "p1"), ("p1", "p1"), ("missing", "p2")],
)
def test_rejects_invalid_team_members(male_id, female_id):
    roster = registered_roster()
    with pytest.raises(RegistrationError):
        roster.create_team("bad", "Bad Team", male_id, female_id)


def test_player_cannot_be_reused_across_teams():
    roster = registered_roster()
    roster.register_player("p5", "Casey", Gender.FEMALE)

    with pytest.raises(RegistrationError, match="more than one team"):
        roster.create_team("team-c", "Team C", "p1", "p5")


def test_rejects_duplicate_player_and_team_names():
    roster = registered_roster()
    with pytest.raises(RegistrationError, match="Player ID already exists"):
        roster.register_player("p1", "Another Alex", Gender.MALE)
    with pytest.raises(RegistrationError, match="Team name already exists"):
        roster.create_team("team-c", "team a", "p1", "p4")


def test_assigns_unique_teams_to_exact_bracket_seeds():
    roster = registered_roster()
    roster.assign_seed("T1", "team-a")
    roster.assign_seed("T2", "team-b")
    definition = load_bracket(DATA_DIR / "4teamD.json")

    assert roster.runtime_entrants(definition) == {"T1": "Team A", "T2": "Team B"}
    with pytest.raises(RegistrationError, match="missing seeds"):
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
