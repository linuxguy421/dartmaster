from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from app.registration.models import Gender, Team
from app.registration.roster import RegistrationError, TournamentRoster


@dataclass(frozen=True, slots=True)
class DrawResult:
    """Teams produced by the registration draw, in draw order."""

    first_gender: Gender
    draw_order: tuple[Gender, Gender]
    mixed_teams: tuple[Team, ...]
    draw_off_teams: tuple[Team, ...]
    female_role_ids: tuple[str, ...] = ()

    @property
    def teams(self) -> tuple[Team, ...]:
        return self.mixed_teams + self.draw_off_teams


def _validate_numbers(
    draws: Mapping[str, int], expected_players: set[str], stage: str
) -> dict[str, int]:
    if set(draws) != expected_players:
        missing = sorted(expected_players - set(draws))
        unexpected = sorted(set(draws) - expected_players)
        details = []
        if missing:
            details.append("missing players: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected players: " + ", ".join(unexpected))
        raise RegistrationError(f"{stage} draw is incomplete: " + "; ".join(details))

    normalized: dict[str, int] = {}
    for player_id, number in draws.items():
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise RegistrationError(
                f"{stage} draw numbers must be positive integers ({player_id})"
            )
        normalized[player_id] = number
    return normalized


def create_teams_from_draw(
    roster: TournamentRoster,
    mixed_draws: Mapping[str, int],
    draw_off_draws: Mapping[str, int] | None = None,
) -> DrawResult:
    """Create mixed teams from matching numbers, then pair all unmatched players.

    Each player draws one positive number in the mixed draw. Numbers must be unique
    within each gender group; a male and female with the same number form a mixed
    team. If exactly two players are unmatched, they automatically form a team.
    When four males remain unmatched, the two with the highest original draw
    numbers take the female playing role and pair, in ascending order, with the
    two lower-numbered unmatched males. Biological gender is unchanged.
    """
    if roster.teams:
        raise RegistrationError("Draw pairing requires a roster with no existing teams")
    if len(roster.players) % 2:
        raise RegistrationError(
            "An even number of players is required to form two-player teams"
        )

    by_gender = {
        gender: {
            player_id
            for player_id, player in roster.players.items()
            if player.gender == gender
        }
        for gender in Gender
    }
    male_count = len(by_gender[Gender.MALE])
    female_count = len(by_gender[Gender.FEMALE])
    if not male_count or not female_count:
        raise RegistrationError("A mixed-team draw requires at least one male and one female")

    first_gender = (
        Gender.MALE if male_count > female_count else Gender.FEMALE
    )
    second_gender = (
        Gender.FEMALE if first_gender == Gender.MALE else Gender.MALE
    )
    expected = by_gender[Gender.MALE] | by_gender[Gender.FEMALE]
    numbers = _validate_numbers(mixed_draws, expected, "Mixed")

    for gender, player_ids in by_gender.items():
        values = [numbers[player_id] for player_id in player_ids]
        if len(values) != len(set(values)):
            raise RegistrationError(
                f"Mixed draw numbers must be unique among {gender.value} players"
            )

    player_for_number = {
        gender: {numbers[player_id]: player_id for player_id in player_ids}
        for gender, player_ids in by_gender.items()
    }
    first_numbers = set(player_for_number[first_gender])
    second_numbers = set(player_for_number[second_gender])
    if not second_numbers.issubset(first_numbers):
        raise RegistrationError(
            f"{second_gender.value.title()} draw numbers must match numbers "
            f"already drawn by {first_gender.value} players"
        )

    shared_numbers = (
        set(player_for_number[Gender.MALE])
        & set(player_for_number[Gender.FEMALE])
    )
    mixed_pairs = [
        (
            player_for_number[Gender.FEMALE][number],
            player_for_number[Gender.MALE][number],
        )
        for number in sorted(shared_numbers)
    ]
    unmatched = expected - {
        player_id for pair in mixed_pairs for player_id in pair
    }

    female_role_ids: tuple[str, ...] = ()
    if len(unmatched) == 2:
        if draw_off_draws:
            raise RegistrationError(
                "No draw-off is needed when exactly two players are unmatched"
            )
        draw_off_pairs = [tuple(sorted(unmatched))]
    elif len(unmatched) == 4 and all(
        roster.players[player_id].gender == Gender.MALE for player_id in unmatched
    ):
        if draw_off_draws:
            raise RegistrationError(
                "The playing-role draw-off is determined by the original draw numbers"
            )
        unmatched_by_draw = sorted(
            unmatched, key=lambda player_id: numbers[player_id]
        )
        male_role_players = unmatched_by_draw[:2]
        female_role_players = unmatched_by_draw[2:]
        female_role_ids = tuple(female_role_players)
        draw_off_pairs = list(zip(male_role_players, female_role_players, strict=True))
    elif unmatched:
        if len(unmatched) % 2:
            raise RegistrationError(
                "The number of unmatched players must be even to form teams"
            )
        if draw_off_draws is None:
            raise RegistrationError("A draw-off is required for more than four unmatched players")
        draw_off_numbers = _validate_numbers(
            draw_off_draws, unmatched, "Draw-off"
        )
        counts = Counter(draw_off_numbers.values())
        invalid = sorted(number for number, count in counts.items() if count != 2)
        if invalid:
            raise RegistrationError(
                "Each draw-off number must be drawn by exactly two unmatched players"
            )
        draw_off_pairs = [
            tuple(
                player_id
                for player_id in sorted(unmatched)
                if draw_off_numbers[player_id] == number
            )
            for number in sorted(counts)
        ]
    else:
        if draw_off_draws:
            raise RegistrationError("No draw-off is needed when every player is matched")
        draw_off_pairs = []

    # Store every team with its female player/playing role first. This keeps
    # player order consistent in registration, bracket labels, and match displays.
    female_role_set = set(female_role_ids)

    def is_female_role(player_id: str) -> bool:
        return (
            player_id in female_role_set
            or roster.players[player_id].gender == Gender.FEMALE
        )

    pairs = mixed_pairs + [
        tuple(sorted(pair, key=lambda player_id: not is_female_role(player_id)))
        for pair in draw_off_pairs
    ]
    next_number = len(roster.teams) + 1
    created: list[Team] = []
    for offset, (player_one_id, player_two_id) in enumerate(pairs):
        team_number = next_number + offset
        created.append(
            roster.create_team(
                f"team-{team_number}",
                f"Team {team_number}",
                player_one_id,
                player_two_id,
            )
        )

    mixed_count = len(mixed_pairs)
    return DrawResult(
        first_gender=first_gender,
        draw_order=(first_gender, second_gender),
        mixed_teams=tuple(created[:mixed_count]),
        draw_off_teams=tuple(created[mixed_count:]),
        female_role_ids=female_role_ids,
    )
