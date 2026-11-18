from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.brackets.loader import BracketDefinition

TEAM_REFERENCE = re.compile(r"^T(?P<seed>[1-9][0-9]*)$")
GAME_REFERENCE = re.compile(r"^(?P<outcome>[WL])-(?P<game>.+)$")


class BracketRuntimeError(ValueError):
    """Raised when a match action is invalid or a bracket cannot be progressed."""


class ChampionshipPhase(StrEnum):
    FIRST_GAME = "first_game"
    RESET = "reset"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class GameResult:
    game_id: str
    winner: str
    loser: str


@dataclass(frozen=True, slots=True)
class ReadyMatch:
    """A schedulable match; GF and GGF share the CHAMPIONSHIP identity."""

    match_id: str
    source_game_id: str
    participants: tuple[str, str]
    phase: ChampionshipPhase | None = None

    @property
    def is_championship(self) -> bool:
        return self.match_id == "CHAMPIONSHIP"


class BracketRuntime:
    """In-memory progression state for one immutable JSON bracket definition.

    Source game order determines priority among ready matches. Source game IDs
    remain the routing/audit keys, while the final and its optional reset are
    exposed as one logical CHAMPIONSHIP match.
    """

    def __init__(
        self,
        definition: BracketDefinition,
        entrants: Mapping[str, str],
    ) -> None:
        self.definition = definition
        self.entrants = dict(entrants)
        self.results: dict[str, GameResult] = {}
        self.placements: dict[str, str] = {}
        self.championship_phase = ChampionshipPhase.FIRST_GAME
        self.champion: str | None = None
        self._validate_entrants()

    def _validate_entrants(self) -> None:
        required = {
            slot
            for game in self.definition.games.values()
            if isinstance(game, dict)
            for slot in game.get("teams", [])
            if isinstance(slot, str) and TEAM_REFERENCE.fullmatch(slot)
        }
        missing = sorted(required - self.entrants.keys())
        if missing:
            raise BracketRuntimeError(
                "Missing entrant assignments for: " + ", ".join(missing)
            )
        if len(set(self.entrants.values())) != len(self.entrants):
            raise BracketRuntimeError("Each seed must be assigned a distinct team")

    def _resolve(self, reference: str) -> str:
        seed_match = TEAM_REFERENCE.fullmatch(reference)
        if seed_match:
            try:
                return self.entrants[reference]
            except KeyError as exc:
                raise BracketRuntimeError(f"No entrant assigned to {reference}") from exc

        game_match = GAME_REFERENCE.fullmatch(reference)
        if game_match:
            game_id = game_match.group("game")
            result = self.results.get(game_id)
            if result is None:
                raise BracketRuntimeError(
                    f"{reference} cannot resolve before {game_id} is complete"
                )
            return result.winner if game_match.group("outcome") == "W" else result.loser

        raise BracketRuntimeError(f"Unsupported participant reference: {reference}")

    def _participants(
        self, game_id: str, *, strict: bool = False
    ) -> tuple[str, str] | None:
        game = self.definition.games.get(game_id)
        if not isinstance(game, dict):
            raise BracketRuntimeError(f"Missing or invalid game definition: {game_id}")
        slots = game.get("teams")
        if not isinstance(slots, list) or len(slots) != 2:
            raise BracketRuntimeError(f"{game_id} must define exactly two participant slots")

        resolved: list[str] = []
        for reference in slots:
            if not isinstance(reference, str):
                raise BracketRuntimeError(f"{game_id} contains a non-string participant reference")
            try:
                resolved.append(self._resolve(reference))
            except BracketRuntimeError:
                if strict:
                    raise
                return None

        if resolved[0] == resolved[1]:
            raise BracketRuntimeError(f"{game_id} resolves to the same team in both slots")
        return resolved[0], resolved[1]

    def ready_matches(self) -> tuple[ReadyMatch, ...]:
        """Return ready matches in source insertion order, hiding standalone GGF."""
        if self.championship_phase == ChampionshipPhase.COMPLETE:
            return ()

        ready: list[ReadyMatch] = []
        for game_id in self.definition.game_order:
            if game_id == "GGF":
                continue
            if game_id == "GF":
                if self.championship_phase == ChampionshipPhase.RESET:
                    participants = self._participants("GGF", strict=True)
                    if participants is not None:
                        ready.append(
                            ReadyMatch(
                                match_id="CHAMPIONSHIP",
                                source_game_id="GGF",
                                participants=participants,
                                phase=ChampionshipPhase.RESET,
                            )
                        )
                elif "GF" not in self.results:
                    participants = self._participants("GF")
                    if participants is not None:
                        ready.append(
                            ReadyMatch(
                                match_id="CHAMPIONSHIP",
                                source_game_id="GF",
                                participants=participants,
                                phase=ChampionshipPhase.FIRST_GAME,
                            )
                        )
                continue

            if game_id not in self.results:
                participants = self._participants(game_id)
                if participants is not None:
                    ready.append(
                        ReadyMatch(
                            match_id=game_id,
                            source_game_id=game_id,
                            participants=participants,
                        )
                    )

        return tuple(ready)

    def record_winner(self, match_id: str, winner: str) -> GameResult:
        """Record a winner by logical match ID; championship reset uses same ID."""
        if match_id == "GGF":
            raise BracketRuntimeError(
                "GGF is a conditional phase of CHAMPIONSHIP, not a schedulable match"
            )
        if match_id == "CHAMPIONSHIP":
            if self.championship_phase == ChampionshipPhase.COMPLETE:
                raise BracketRuntimeError("Championship is already complete")
            game_id = (
                "GGF"
                if self.championship_phase == ChampionshipPhase.RESET
                else "GF"
            )
        else:
            game_id = match_id
            if game_id not in self.definition.games:
                raise BracketRuntimeError(f"Unknown match: {match_id}")
            if game_id in {"GF", "GGF"}:
                raise BracketRuntimeError(
                    "Use CHAMPIONSHIP to record the championship result"
                )
            if game_id in self.results:
                raise BracketRuntimeError(f"{game_id} has already been completed")

        participants = self._participants(game_id)
        if participants is None:
            raise BracketRuntimeError(f"{game_id} is not ready; both participants must resolve")
        if winner not in participants:
            raise BracketRuntimeError(
                f"Winner {winner!r} is not a participant in {game_id}: {participants}"
            )
        loser = participants[1] if winner == participants[0] else participants[0]
        result = GameResult(game_id=game_id, winner=winner, loser=loser)
        self.results[game_id] = result

        if game_id == "GF":
            if winner == participants[0]:
                self.champion = winner
                self.championship_phase = ChampionshipPhase.COMPLETE
                self._record_terminal_route("GF", "winner_advances_to", winner)
                self._record_terminal_route("GF", "loser_drops_to", loser)
                reset_game = self.definition.games.get("GGF")
                second_place_route = (
                    reset_game.get("loser_drops_to", {})
                    if isinstance(reset_game, dict)
                    else {}
                )
                if (
                    isinstance(second_place_route, dict)
                    and second_place_route.get("rank") == "2nd"
                ):
                    self.placements["2nd"] = loser
            else:
                self.championship_phase = ChampionshipPhase.RESET
        elif game_id == "GGF":
            self.champion = winner
            self.championship_phase = ChampionshipPhase.COMPLETE
            self._record_terminal_route("GGF", "winner_advances_to", winner)
            self._record_terminal_route("GGF", "loser_drops_to", loser)
        else:
            self._record_terminal_route(game_id, "winner_advances_to", winner)
            self._record_terminal_route(game_id, "loser_drops_to", loser)

        return result

    def _record_terminal_route(self, game_id: str, route_name: str, team: str) -> None:
        game = self.definition.games.get(game_id, {})
        route = game.get(route_name, {}) if isinstance(game, dict) else {}
        if isinstance(route, dict) and route.get("result") == "ELIMINATED":
            rank = route.get("rank")
            if isinstance(rank, str):
                self.placements[rank] = team
