from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.brackets.loader import BracketDefinition
from app.registration.models import Gender, Player, Team


class RegistrationError(ValueError):
    """Raised when a player, team, or bracket-seed assignment is invalid."""


class TournamentRoster:
    """Registration pool, two-player teams, and bracket seed assignments."""

    def __init__(self) -> None:
        self.players: dict[str, Player] = {}
        self.teams: dict[str, Team] = {}
        self.seed_assignments: dict[str, str] = {}

    def register_player(
        self, player_id: str, display_name: str, gender: Gender | str, paid: bool = False
    ) -> Player:
        player_id = player_id.strip()
        display_name = display_name.strip()
        if not player_id:
            raise RegistrationError("Player ID cannot be empty")
        if not display_name:
            raise RegistrationError("Player display name cannot be empty")
        if player_id in self.players:
            raise RegistrationError(f"Player ID already exists: {player_id}")
        normalized_name = display_name.casefold()
        if any(player.display_name.casefold() == normalized_name for player in self.players.values()):
            raise RegistrationError(f"Player name already registered: {display_name}")
        try:
            normalized_gender = Gender(gender)
        except ValueError as exc:
            raise RegistrationError("Player gender must be 'male' or 'female'") from exc

        player = Player(player_id, display_name, normalized_gender, bool(paid))
        self.players[player_id] = player
        return player

    def create_team(
        self,
        team_id: str,
        name: str,
        player_one_id: str,
        player_two_id: str,
    ) -> Team:
        team_id = team_id.strip()
        name = name.strip()
        if not team_id:
            raise RegistrationError("Team ID cannot be empty")
        if not name:
            raise RegistrationError("Team name cannot be empty")
        if team_id in self.teams:
            raise RegistrationError(f"Team ID already exists: {team_id}")
        if any(team.name.casefold() == name.casefold() for team in self.teams.values()):
            raise RegistrationError(f"Team name already exists: {name}")
        if player_one_id == player_two_id:
            raise RegistrationError("A team must contain two distinct players")

        for player_id in (player_one_id, player_two_id):
            if player_id not in self.players:
                raise RegistrationError(f"Unknown player: {player_id}")

        assigned = {
            player_id
            for team in self.teams.values()
            for player_id in (team.player_one_id, team.player_two_id)
        }
        reused = assigned.intersection({player_one_id, player_two_id})
        if reused:
            raise RegistrationError(
                "A player cannot belong to more than one team: "
                + ", ".join(sorted(reused))
            )

        team = Team(team_id, name, player_one_id, player_two_id)
        self.teams[team_id] = team
        return team

    def assign_seed(self, seed: str, team_id: str) -> None:
        seed = seed.strip()
        if not seed:
            raise RegistrationError("Bracket seed cannot be empty")
        if team_id not in self.teams:
            raise RegistrationError(f"Unknown team: {team_id}")
        if seed in self.seed_assignments:
            raise RegistrationError(f"Seed is already assigned: {seed}")
        if team_id in self.seed_assignments.values():
            raise RegistrationError(f"Team is already assigned to a seed: {team_id}")
        self.seed_assignments[seed] = team_id

    def validate_for_bracket(self, definition: BracketDefinition) -> None:
        required = {
            reference
            for game in definition.games.values()
            if isinstance(game, dict)
            for reference in game.get("teams", [])
            if isinstance(reference, str)
            and reference.startswith("T")
            and reference[1:].isdigit()
        }
        missing = sorted(required - self.seed_assignments.keys())
        unexpected = sorted(self.seed_assignments.keys() - required)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing seeds: " + ", ".join(missing))
            if unexpected:
                details.append("unknown seeds: " + ", ".join(unexpected))
            raise RegistrationError("Roster does not match bracket: " + "; ".join(details))

    def runtime_entrants(self, definition: BracketDefinition) -> dict[str, str]:
        self.validate_for_bracket(definition)
        return {
            seed: f"{self.players[self.teams[team_id].player_one_id].display_name} & {self.players[self.teams[team_id].player_two_id].display_name}"
            for seed, team_id in self.seed_assignments.items()
        }

    def team_for_seed(self, seed: str) -> Team:
        try:
            return self.teams[self.seed_assignments[seed]]
        except KeyError as exc:
            raise RegistrationError(f"No team assigned to seed {seed}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "players": [
                {
                    "player_id": player.player_id,
                    "display_name": player.display_name,
                    "gender": player.gender.value,
                    "paid": player.paid,
                }
                for player in self.players.values()
            ],
            "teams": [
                {
                    "team_id": team.team_id,
                    "name": team.name,
                    "player_one_id": team.player_one_id,
                    "player_two_id": team.player_two_id,
                }
                for team in self.teams.values()
            ],
            "seed_assignments": dict(self.seed_assignments),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TournamentRoster:
        if not isinstance(data, Mapping):
            raise RegistrationError("Persisted registration must be an object")
        roster = cls()
        try:
            players = data["players"]
            teams = data["teams"]
            seeds = data["seed_assignments"]
            if not isinstance(players, list) or not isinstance(teams, list):
                raise RegistrationError("Persisted players and teams must be lists")
            if not isinstance(seeds, Mapping):
                raise RegistrationError("Persisted seed assignments must be an object")
            for raw in players:
                roster.register_player(
                    raw["player_id"], raw["display_name"], raw["gender"], raw.get("paid", False)
                )
            for raw in teams:
                # Accept the previous mixed-doubles snapshot shape while writing only
                # the gender-neutral two-player shape going forward.
                player_one_id = raw.get("player_one_id", raw.get("male_player_id"))
                player_two_id = raw.get("player_two_id", raw.get("female_player_id"))
                roster.create_team(
                    raw["team_id"], raw["name"], player_one_id, player_two_id
                )
            for seed, team_id in seeds.items():
                roster.assign_seed(seed, team_id)
        except (KeyError, TypeError, AttributeError) as exc:
            raise RegistrationError(f"Invalid persisted registration: {exc}") from exc
        return roster
