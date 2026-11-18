from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from app.brackets.runtime import (
    BracketRuntime,
    BracketRuntimeError,
    ChampionshipPhase,
    ReadyMatch,
)


class SchedulerMode(StrEnum):
    """Legacy snapshot value; new tournaments always use operator assignment."""

    MANUAL = "manual"
    AUTO = "auto"


class BoardSchedulerError(ValueError):
    """Raised when a board scheduling operation is invalid."""


@dataclass(frozen=True, slots=True)
class BoardAssignment:
    board_id: int
    match: ReadyMatch
    blocked_reason: str | None = None


class BoardScheduler:
    """Four always-available boards with explicit operator match assignment."""

    BOARD_COUNT = 4
    RECOMMENDATION_ORDER = (1, 3, 2, 4)

    def __init__(
        self,
        board_count: int = 4,
        mode: SchedulerMode = SchedulerMode.MANUAL,
    ) -> None:
        if board_count < 1 or board_count > self.BOARD_COUNT:
            raise BoardSchedulerError("Dartmaster always provides exactly 4 boards")
        self.board_count = self.BOARD_COUNT
        self.mode = SchedulerMode.MANUAL
        self._assignments: dict[int, BoardAssignment] = {}

    @property
    def enabled_boards(self) -> tuple[int, ...]:
        """All physical boards are always available for operator assignment."""
        return (1, 2, 3, 4)

    @property
    def assignments(self) -> tuple[BoardAssignment, ...]:
        return tuple(self._assignments[key] for key in sorted(self._assignments))

    @property
    def free_boards(self) -> tuple[int, ...]:
        return tuple(board for board in range(1, 5) if board not in self._assignments)

    def _validate_board(self, board_id: int) -> None:
        if not isinstance(board_id, int) or isinstance(board_id, bool) or not 1 <= board_id <= 4:
            raise BoardSchedulerError("Board must be an integer from 1 to 4")

    def ready_matches(self, runtime: BracketRuntime) -> tuple[ReadyMatch, ...]:
        assigned = {item.match.match_id for item in self._assignments.values()}
        return tuple(
            match for match in runtime.ready_matches()
            if match.match_id not in assigned
        )

    def recommended_boards(self, runtime: BracketRuntime) -> tuple[int, ...]:
        """Suggest a spread-out set of free boards; never assign matches."""
        count = min(len(self.ready_matches(runtime)), len(self.free_boards))
        if not count:
            return ()
        free = set(self.free_boards)
        if count == 2:
            for pair in ((1, 3), (2, 4)):
                if set(pair).issubset(free):
                    return pair
        return tuple(board for board in self.RECOMMENDATION_ORDER if board in free)[:count]

    def assign(self, board_id: int, match_id: str, runtime: BracketRuntime) -> BoardAssignment:
        self._validate_board(board_id)
        if board_id in self._assignments:
            raise BoardSchedulerError(f"Board {board_id} already has an active match")
        match = next(
            (candidate for candidate in self.ready_matches(runtime)
             if candidate.match_id == match_id),
            None,
        )
        if match is None:
            raise BoardSchedulerError(
                f"Match {match_id!r} is not ready or is already assigned"
            )
        assignment = BoardAssignment(board_id, match)
        self._assignments[board_id] = assignment
        return assignment

    def start_available(self, runtime: BracketRuntime) -> tuple[BoardAssignment, ...]:
        """Compatibility no-op: ready matches are never assigned automatically."""
        return self.assignments

    def snapshot(self) -> dict[str, Any]:
        return {
            "board_count": 4,
            "mode": SchedulerMode.MANUAL.value,
            "enabled_boards": [1, 2, 3, 4],
            "assignments": [
                {
                    "board_id": item.board_id,
                    "match": {
                        "match_id": item.match.match_id,
                        "source_game_id": item.match.source_game_id,
                        "participants": list(item.match.participants),
                        "phase": item.match.phase.value if item.match.phase else None,
                    },
                    "blocked_reason": item.blocked_reason,
                }
                for item in self.assignments
            ],
        }

    @classmethod
    def from_snapshot(
        cls, snapshot: dict[str, Any], runtime: BracketRuntime
    ) -> BoardScheduler:
        try:
            # Older snapshots may have configured fewer boards or auto mode.
            scheduler = cls()
            assignments = snapshot["assignments"]
            if not isinstance(assignments, list):
                raise TypeError("assignments must be a list")
            for raw in assignments:
                board_id = raw["board_id"]
                scheduler._validate_board(board_id)
                if board_id in scheduler._assignments:
                    raise ValueError(f"duplicate assignment for board {board_id}")
                match_data = raw["match"]
                phase = match_data.get("phase")
                match = ReadyMatch(
                    match_id=match_data["match_id"],
                    source_game_id=match_data["source_game_id"],
                    participants=tuple(match_data["participants"]),
                    phase=ChampionshipPhase(phase) if phase else None,
                )
                blocked_reason = raw.get("blocked_reason")
                if blocked_reason is None:
                    candidates = {
                        candidate.match_id: candidate
                        for candidate in runtime.ready_matches()
                    }
                    if candidates.get(match.match_id) != match:
                        raise ValueError(
                            f"board {board_id} assignment does not match current bracket state"
                        )
                elif not (
                    match.match_id == "CHAMPIONSHIP"
                    and match.source_game_id == "GGF"
                    and match.phase == ChampionshipPhase.RESET
                    and runtime.championship_phase == ChampionshipPhase.RESET
                    and isinstance(blocked_reason, str)
                    and bool(blocked_reason)
                    and match.participants == runtime._participants("GF", strict=True)
                ):
                    raise ValueError("only a validly reserved blocked championship reset may occupy a board")
                scheduler._assignments[board_id] = BoardAssignment(
                    board_id, match, blocked_reason
                )
            assigned_matches = [item.match.match_id for item in scheduler._assignments.values()]
            if len(assigned_matches) != len(set(assigned_matches)):
                raise ValueError("a logical match cannot be assigned to multiple boards")
            return scheduler
        except (KeyError, TypeError, ValueError) as exc:
            raise BoardSchedulerError(f"Invalid scheduler snapshot: {exc}") from exc

    def complete(
        self, board_id: int, winner: str, runtime: BracketRuntime
    ) -> BoardAssignment | None:
        """Record a winner; retain the board only for the conditional reset."""
        self._validate_board(board_id)
        assignment = self._assignments.get(board_id)
        if assignment is None:
            raise BoardSchedulerError(f"Board {board_id} has no assigned match")

        runtime.record_winner(assignment.match.match_id, winner)
        if (
            assignment.match.is_championship
            and runtime.championship_phase == ChampionshipPhase.RESET
        ):
            try:
                reset_match = next(
                    match for match in runtime.ready_matches()
                    if match.match_id == "CHAMPIONSHIP"
                )
                updated = BoardAssignment(board_id, reset_match)
            except (BracketRuntimeError, StopIteration) as exc:
                updated = replace(
                    assignment,
                    match=replace(
                        assignment.match,
                        source_game_id="GGF",
                        phase=ChampionshipPhase.RESET,
                    ),
                    blocked_reason=str(exc) or "Championship reset is not ready",
                )
            self._assignments[board_id] = updated
            return updated

        del self._assignments[board_id]
        return None
