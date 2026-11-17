import pytest

from app.registration import Gender, RegistrationError, TournamentRoster
from app.registration.draw import create_teams_from_draw


def roster_with_counts(males: int, females: int) -> TournamentRoster:
    roster = TournamentRoster()
    for index in range(males):
        roster.register_player(f"m{index + 1}", f"Male {index + 1}", Gender.MALE)
    for index in range(females):
        roster.register_player(f"f{index + 1}", f"Female {index + 1}", Gender.FEMALE)
    return roster


def test_larger_male_group_draws_first_and_surplus_redraws():
    roster = roster_with_counts(6, 4)
    mixed_draws = {
        "m1": 1, "m2": 2, "m3": 3, "m4": 4, "m5": 5, "m6": 6,
        "f1": 1, "f2": 2, "f3": 3, "f4": 4,
    }

    result = create_teams_from_draw(
        roster, mixed_draws, {"m5": 1, "m6": 1}
    )

    assert result.first_gender == Gender.MALE
    assert result.draw_order == (Gender.MALE, Gender.FEMALE)
    assert len(result.mixed_teams) == 4
    assert len(result.draw_off_teams) == 1
    final_team = result.draw_off_teams[0]
    assert {final_team.player_one_id, final_team.player_two_id} == {"m5", "m6"}
    assert len(roster.teams) == 5


def test_larger_female_group_draws_first():
    roster = roster_with_counts(2, 4)
    result = create_teams_from_draw(
        roster,
        {"m1": 1, "m2": 2, "f1": 1, "f2": 2, "f3": 3, "f4": 4},
        {"f3": 1, "f4": 1},
    )

    assert result.first_gender == Gender.FEMALE
    assert result.draw_order == (Gender.FEMALE, Gender.MALE)
    assert len(result.mixed_teams) == 2
    assert len(result.draw_off_teams) == 1
    assert {result.draw_off_teams[0].player_one_id,
            result.draw_off_teams[0].player_two_id} == {"f3", "f4"}


def test_equal_groups_default_to_females_drawing_first():
    roster = roster_with_counts(2, 2)
    result = create_teams_from_draw(
        roster, {"m1": 1, "m2": 2, "f1": 1, "f2": 2}
    )
    assert result.first_gender == Gender.FEMALE
    assert result.draw_order == (Gender.FEMALE, Gender.MALE)
    assert len(result.teams) == 2


def test_four_unmatched_players_redraw_into_two_teams():
    roster = roster_with_counts(6, 2)
    result = create_teams_from_draw(
        roster,
        {"m1": 1, "m2": 2, "m3": 3, "m4": 4, "m5": 5, "m6": 6,
         "f1": 1, "f2": 2},
        {"m3": 1, "m4": 1, "m5": 2, "m6": 2},
    )
    assert len(result.mixed_teams) == 2
    assert len(result.draw_off_teams) == 2


def test_rejects_odd_unmatched_count():
    roster = roster_with_counts(3, 2)
    with pytest.raises(RegistrationError, match="must be even"):
        create_teams_from_draw(
            roster,
            {"m1": 1, "m2": 2, "m3": 3, "f1": 1, "f2": 2},
            {"m3": 1},
        )



def test_second_group_must_draw_from_first_groups_numbers():
    roster = roster_with_counts(3, 2)
    with pytest.raises(RegistrationError, match="must match numbers already drawn"):
        create_teams_from_draw(
            roster,
            {"m1": 1, "m2": 2, "m3": 3, "f1": 1, "f2": 4},
            {"m2": 1, "m3": 1},
        )

def test_rejects_duplicate_numbers_within_gender():
    roster = roster_with_counts(2, 2)
    with pytest.raises(RegistrationError, match="unique among male"):
        create_teams_from_draw(
            roster, {"m1": 1, "m2": 1, "f1": 1, "f2": 2}
        )


def test_draw_off_number_must_identify_exactly_two_players():
    roster = roster_with_counts(4, 2)
    with pytest.raises(RegistrationError, match="exactly two"):
        create_teams_from_draw(
            roster,
            {"m1": 1, "m2": 2, "m3": 3, "m4": 4, "f1": 1, "f2": 2},
            {"m3": 1, "m4": 2},
        )


def test_requires_draw_off_when_players_are_unmatched():
    roster = roster_with_counts(4, 2)
    with pytest.raises(RegistrationError, match="draw-off is required"):
        create_teams_from_draw(
            roster,
            {"m1": 1, "m2": 2, "m3": 3, "m4": 4, "f1": 1, "f2": 2},
        )


def test_draw_does_not_mutate_roster_when_draw_validation_fails():
    roster = roster_with_counts(4, 2)
    with pytest.raises(RegistrationError):
        create_teams_from_draw(
            roster,
            {"m1": 1, "m2": 2, "m3": 3, "m4": 4, "f1": 1, "f2": 2},
            {"m3": 1, "m4": 2},
        )
    assert roster.teams == {}
