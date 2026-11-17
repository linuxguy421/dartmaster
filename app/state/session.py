from __future__ import annotations

from typing import Any

from app.brackets.loader import BracketDefinition
from app.brackets.runtime import BracketRuntime
from app.brackets.scheduler import BoardScheduler, SchedulerMode
from app.registration.roster import TournamentRoster
from app.state.store import TournamentStateStore


class TournamentSession:
    """Coordinates bracket progression, board allocation, and durable state."""

    def __init__(
        self,
        tournament_id: str,
        bracket_file: str,
        runtime: BracketRuntime,
        scheduler: BoardScheduler,
        store: TournamentStateStore,
        roster: TournamentRoster | None = None,
    ) -> None:
        self.tournament_id = tournament_id
        self.bracket_file = bracket_file
        self.runtime = runtime
        self.scheduler = scheduler
        self.store = store
        self.roster = roster

    @classmethod
    def create(
        cls,
        tournament_id: str,
        bracket_file: str,
        definition: BracketDefinition,
        entrants: dict[str, str],
        store: TournamentStateStore,
        *,
        board_count: int = 4,
        mode: SchedulerMode = SchedulerMode.MANUAL,
        roster: TournamentRoster | None = None,
    ) -> TournamentSession:
        if roster is not None:
            roster.validate_for_bracket(definition)
            if roster.runtime_entrants(definition) != entrants:
                raise ValueError("Roster team assignments must match runtime entrants")
        runtime = BracketRuntime(definition, entrants)
        scheduler = BoardScheduler(board_count=board_count, mode=mode)
        session = cls(tournament_id, bracket_file, runtime, scheduler, store, roster)
        scheduler.start_available(runtime)
        session._save("tournament_created", {"entrant_count": len(entrants)})
        return session

    @classmethod
    def restore(
        cls,
        tournament_id: str,
        definition: BracketDefinition,
        store: TournamentStateStore,
    ) -> TournamentSession:
        runtime, scheduler, bracket_file, roster = store.restore(tournament_id, definition)
        return cls(tournament_id, bracket_file, runtime, scheduler, store, roster)

    def _save(self, event_type: str, payload: dict[str, Any]) -> None:
        self.store.save(
            self.tournament_id,
            self.bracket_file,
            self.runtime,
            self.scheduler,
            event_type=event_type,
            event_payload=payload,
            roster=self.roster,
        )

    def _rollback(self) -> None:
        self.runtime, self.scheduler, _, self.roster = self.store.restore(
            self.tournament_id, self.runtime.definition
        )

    def _save_or_rollback(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            self._save(event_type, payload)
        except Exception:
            self._rollback()
            raise

    def _assignment_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "board_id": assignment.board_id,
                "match_id": assignment.match.match_id,
                "source_game_id": assignment.match.source_game_id,
            }
            for assignment in self.scheduler.assignments
        ]

    def enable_board(self, board_id: int) -> None:
        self.scheduler.enable_board(board_id)
        self.scheduler.start_available(self.runtime)
        self._save_or_rollback(
            "board_enabled",
            {"board_id": board_id, "assignments": self._assignment_summary()},
        )

    def disable_board(self, board_id: int) -> None:
        self.scheduler.disable_board(board_id)
        self._save_or_rollback("board_disabled", {"board_id": board_id})

    def set_scheduler_mode(self, mode: SchedulerMode) -> None:
        self.scheduler.set_mode(mode)
        self.scheduler.start_available(self.runtime)
        self._save_or_rollback(
            "scheduler_mode_changed",
            {"mode": self.scheduler.mode.value, "assignments": self._assignment_summary()},
        )

    def start_available(self) -> None:
        before = self.scheduler.snapshot()
        self.scheduler.start_available(self.runtime)
        if self.scheduler.snapshot() != before:
            self._save_or_rollback(
                "matches_assigned", {"assignments": self._assignment_summary()}
            )

    def complete_match(self, board_id: int, winner: str) -> None:
        assignment = next(
            (item for item in self.scheduler.assignments if item.board_id == board_id),
            None,
        )
        if assignment is None:
            raise ValueError(f"Board {board_id} has no assigned match")

        match_id = assignment.match.match_id
        source_game_id = assignment.match.source_game_id
        self.scheduler.complete(board_id, winner, self.runtime)
        self.scheduler.start_available(self.runtime)
        self._save_or_rollback(
            "match_completed",
            {
                "board_id": board_id,
                "match_id": match_id,
                "source_game_id": source_game_id,
                "winner": winner,
                "championship_phase": self.runtime.championship_phase.value,
                "assignments": self._assignment_summary(),
            },
        )
