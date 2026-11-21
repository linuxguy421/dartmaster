from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GAME_REF = re.compile(r"^[WL]-(?P<game>.+)$")
TEAM_REF = re.compile(r"^T[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class BracketDiagnostic:
    game_id: str
    message: str


@dataclass(frozen=True, slots=True)
class BracketDefinition:
    """JSON bracket data; game insertion order is retained exactly as authored."""

    tournament_name: str
    prizes: dict[str, int]
    prizes_with_side_pot: dict[str, int]
    side_pot_amount: int
    side_pot_contribution_per_player: int
    currency: str
    games: dict[str, dict[str, Any]]
    source_path: Path
    diagnostics: tuple[BracketDiagnostic, ...]

    @property
    def game_order(self) -> tuple[str, ...]:
        return tuple(self.games)


class BracketLoadError(ValueError):
    """Raised when a bracket cannot be parsed or has invalid basic structure."""


def _diagnose(games: dict[str, Any]) -> tuple[BracketDiagnostic, ...]:
    diagnostics: list[BracketDiagnostic] = []
    known_games = set(games)

    for game_id, game in games.items():
        if not isinstance(game, dict):
            diagnostics.append(BracketDiagnostic(game_id, "Game definition is not an object"))
            continue

        slots = game.get("teams")
        if not isinstance(slots, list) or len(slots) != 2:
            diagnostics.append(BracketDiagnostic(game_id, "Expected exactly two team slots"))
            continue

        for slot in slots:
            if not isinstance(slot, str):
                diagnostics.append(BracketDiagnostic(game_id, f"Invalid slot reference: {slot!r}"))
                continue
            match = GAME_REF.fullmatch(slot)
            if match and match.group("game") not in known_games:
                diagnostics.append(
                    BracketDiagnostic(game_id, f"{slot} references missing game {match.group('game')}")
                )
            elif not match and not TEAM_REF.fullmatch(slot):
                diagnostics.append(BracketDiagnostic(game_id, f"Unrecognized slot reference: {slot}"))

        for route_name in ("winner_advances_to", "loser_drops_to"):
            route = game.get(route_name)
            if not isinstance(route, dict):
                diagnostics.append(BracketDiagnostic(game_id, f"Missing or invalid {route_name}"))
                continue
            target = route.get("game")
            if target is not None and target not in known_games:
                diagnostics.append(
                    BracketDiagnostic(game_id, f"{route_name} references missing game {target}")
                )
            elif target is not None and route.get("slot") not in (0, 1):
                diagnostics.append(
                    BracketDiagnostic(game_id, f"{route_name} target slot must be 0 or 1")
                )
            elif target is not None:
                target_game = games.get(target)
                target_slots = target_game.get("teams") if isinstance(target_game, dict) else None
                outcome = "W" if route_name == "winner_advances_to" else "L"
                expected_reference = f"{outcome}-{game_id}"
                target_slot = route["slot"]
                if (
                    isinstance(target_slots, list)
                    and len(target_slots) == 2
                    and target_slots[target_slot] != expected_reference
                ):
                    diagnostics.append(
                        BracketDiagnostic(
                            game_id,
                            f"{route_name} points to {target}[{target_slot}], "
                            f"but that slot references {target_slots[target_slot]!r} "
                            f"instead of {expected_reference}",
                        )
                    )
            elif target is None and not isinstance(route.get("result"), str):
                diagnostics.append(
                    BracketDiagnostic(game_id, f"{route_name} must specify game or result")
                )

    return tuple(diagnostics)


def load_bracket(path: str | Path) -> BracketDefinition:
    """Load JSON without normalizing, sorting, or repairing the source definition."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BracketLoadError(f"Unable to read {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BracketLoadError(f"Invalid JSON in {source}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("games"), dict):
        raise BracketLoadError(f"{source}: expected an object containing a games object")

    games = payload["games"]
    if not games:
        raise BracketLoadError(f"{source}: games object is empty")

    prizes = payload.get("prizes", {})
    if not isinstance(prizes, dict):
        raise BracketLoadError(f"{source}: prizes must be an object")
    prizes_with_side_pot = payload.get("prizes_with_side_pot", {})
    if not isinstance(prizes_with_side_pot, dict):
        raise BracketLoadError(f"{source}: prizes_with_side_pot must be an object")

    return BracketDefinition(
        tournament_name=str(payload.get("tournament_name", source.stem)),
        prizes={str(place): int(amount) for place, amount in prizes.items()},
        prizes_with_side_pot={
            str(place): int(amount) for place, amount in prizes_with_side_pot.items()
        },
        side_pot_amount=int(payload.get("side_pot_amount", 0)),
        side_pot_contribution_per_player=int(payload.get("side_pot_contribution_per_player", 0)),
        currency=str(payload.get("currency", "USD")),
        games=games,
        source_path=source,
        diagnostics=_diagnose(games),
    )


def available_brackets(directory: str | Path) -> list[Path]:
    """Return bracket files in ascending team-count order, not match execution order."""
    root = Path(directory)
    return sorted(root.glob("*teamD.json"), key=lambda p: int(p.name.split("team")[0]))
