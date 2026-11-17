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
    """Assign ready bracket matches to operator-enabled boards.

    Manual mode starts with no boards enabled; the operator explicitly enables
    the boards that should be in service. Auto mode makes every configured
    board eligible. Match priority always follows the bracket runtime's order.
    """

    def __init__(
        self,
        board_count: int = 4,
        mode: SchedulerMode = SchedulerMode.MANUAL,
    ) -> None:
        if board_count < 1:
            raise BoardSchedulerError("board_count must be at least 1")
        self.board_count = board_count
        self.mode = SchedulerMode(mode)
        self._enabled_boards: set[int] = set()
        self._assignments: dict[int, BoardAssignment] = {}

    @property
    def enabled_boards(self) -> tuple[int, ...]:
        if self.mode == SchedulerMode.AUTO:
            return tuple(range(1, self.board_count + 1))
        return tuple(sorted(self._enabled_boards))

    @property
    def assignments(self) -> tuple[BoardAssignment, ...]:
        return tuple(self._assignments[key] for key in sorted(self._assignments))

    def set_mode(self, mode: SchedulerMode) -> None:
        self.mode = SchedulerMode(mode)

    def enable_board(self, board_id: int) -> None:
        self._validate_board(board_id)
        if self.mode == SchedulerMode.MANUAL:
            self._enabled_boards.add(board_id)

    def disable_board(self, board_id: int) -> None:
        self._validate_board(board_id)
        if board_id in self._assignments:
            raise BoardSchedulerError(
                f"Board {board_id} has an active match and cannot be disabled"
            )
        self._enabled_boards.discard(board_id)

    def _validate_board(self, board_id: int) -> None:
        if not isinstance(board_id, int) or not 1 <= board_id <= self.board_count:
            raise BoardSchedulerError(
                f"Board must be an integer from 1 to {self.board_count}"
            )

    def start_available(self, runtime: BracketRuntime) -> tuple[BoardAssignment, ...]:
        """Fill enabled, idle boards using the earliest ready unassigned matches."""
        occupied_match_ids = {
            assignment.match.match_id for assignment in self._assignments.values()
        }
        free_boards = [
            board_id
            for board_id in self.enabled_boards
            if board_id not in self._assignments
        ]
        if not free_boards:
            return self.assignments

        ready = [
            match
            for match in runtime.ready_matches()
            if match.match_id not in occupied_match_ids
        ]
        for board_id, match in zip(free_boards, ready):
            self._assignments[board_id] = BoardAssignment(board_id, match)
        return self.assignments


    def snapshot(self) -> dict[str, Any]:
        return {
            "board_count": self.board_count,
            "mode": self.mode.value,
            "enabled_boards": list(sorted(self._enabled_boards)),
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
            scheduler = cls(
                board_count=int(snapshot["board_count"]),
                mode=SchedulerMode(snapshot["mode"]),
            )
            enabled = snapshot["enabled_boards"]
            if not isinstance(enabled, list):
                raise ValueError("enabled_boards must be a list")
            for board_id in enabled:
                scheduler._validate_board(board_id)
                scheduler._enabled_boards.add(board_id)

            assignments = snapshot["assignments"]
            if not isinstance(assignments, list):
                raise ValueError("assignments must be a list")
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
                    and runtime.championship_phase == ChampionshipPhase.RESET
                ):
                    raise ValueError("only a blocked championship reset may reserve a board")
                scheduler._assignments[board_id] = BoardAssignment(
                    board_id, match, blocked_reason
                )
            assigned_matches = [
                item.match.match_id for item in scheduler._assignments.values()
            ]
            if len(assigned_matches) != len(set(assigned_matches)):
                raise ValueError("a logical match cannot be assigned to multiple boards")
            if scheduler.mode == SchedulerMode.AUTO and scheduler._enabled_boards:
                raise ValueError("auto mode cannot persist manual board selections")
            return scheduler
        except (KeyError, TypeError, ValueError) as exc:
            raise BoardSchedulerError(f"Invalid scheduler snapshot: {exc}") from exc

    def complete(
        self, board_id: int, winner: str, runtime: BracketRuntime
    ) -> BoardAssignment | None:
        """Record a board's winner; retain championship board for a reset."""
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
                        match
                        for match in runtime.ready_matches()
                        if match.match_id == "CHAMPIONSHIP"
                    )
                updated = BoardAssignment(board_id, reset_match)
            except (BracketRuntimeError, StopIteration) as exc:
                # Keep the board reserved even when the source reset definition
                # is malformed; never let another match take this championship's board.
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
