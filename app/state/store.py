from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.brackets.loader import BracketDefinition
from app.brackets.runtime import BracketRuntime, BracketRuntimeError
from app.brackets.scheduler import BoardScheduler, BoardSchedulerError
from app.registration.roster import RegistrationError, TournamentRoster

SCHEMA_VERSION = 1


class TournamentStoreError(RuntimeError):
    """Raised when persisted tournament state is missing or invalid."""


class TournamentStateStore:
    """SQLite-backed, atomic snapshots and append-only operator event history."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tournaments (
                    tournament_id TEXT PRIMARY KEY,
                    bracket_file TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tournament_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id TEXT NOT NULL REFERENCES tournaments(tournament_id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tournament_events_tournament
                ON tournament_events(tournament_id, event_id)
                """
            )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _snapshot(
        bracket_file: str,
        runtime: BracketRuntime,
        scheduler: BoardScheduler,
        roster: TournamentRoster | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "bracket_file": bracket_file,
            "entrants": dict(runtime.entrants),
            "registration": roster.to_dict() if roster is not None else None,
            "runtime": {
                "results": [
                    {
                        "game_id": result.game_id,
                        "winner": result.winner,
                        "loser": result.loser,
                    }
                    for result in runtime.results.values()
                ],
                "placements": dict(runtime.placements),
                "championship_phase": runtime.championship_phase.value,
                "champion": runtime.champion,
            },
            "scheduler": scheduler.snapshot(),
        }

    def save(
        self,
        tournament_id: str,
        bracket_file: str,
        runtime: BracketRuntime,
        scheduler: BoardScheduler,
        *,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
        roster: TournamentRoster | None = None,
    ) -> None:
        if not tournament_id.strip():
            raise TournamentStoreError("tournament_id cannot be empty")
        if not bracket_file.strip():
            raise TournamentStoreError("bracket_file cannot be empty")
        if not event_type.strip():
            raise TournamentStoreError("event_type cannot be empty")

        snapshot = self._snapshot(bracket_file, runtime, scheduler, roster)
        state_json = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
        payload_json = json.dumps(event_payload or {}, separators=(",", ":"), sort_keys=True)
        now = self._utc_now()

        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO tournaments (
                        tournament_id, bracket_file, state_json, schema_version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tournament_id) DO UPDATE SET
                        bracket_file = excluded.bracket_file,
                        state_json = excluded.state_json,
                        schema_version = excluded.schema_version,
                        updated_at = excluded.updated_at
                    """,
                    (tournament_id, bracket_file, state_json, SCHEMA_VERSION, now, now),
                )
                connection.execute(
                    """
                    INSERT INTO tournament_events (
                        tournament_id, event_type, payload_json, occurred_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (tournament_id, event_type, payload_json, now),
                )
        except sqlite3.Error as exc:
            raise TournamentStoreError(f"Could not save tournament state: {exc}") from exc

    def load(self, tournament_id: str) -> dict[str, Any]:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT state_json, schema_version FROM tournaments WHERE tournament_id = ?",
                    (tournament_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise TournamentStoreError(f"Could not load tournament state: {exc}") from exc

        if row is None:
            raise TournamentStoreError(f"Unknown tournament: {tournament_id}")
        if row["schema_version"] != SCHEMA_VERSION:
            raise TournamentStoreError(
                f"Unsupported state schema version: {row['schema_version']}"
            )
        try:
            snapshot = json.loads(row["state_json"])
        except json.JSONDecodeError as exc:
            raise TournamentStoreError("Persisted tournament snapshot is invalid JSON") from exc
        if not isinstance(snapshot, dict):
            raise TournamentStoreError("Persisted tournament snapshot must be an object")
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            raise TournamentStoreError("Snapshot schema version does not match database record")
        return snapshot

    def restore(
        self, tournament_id: str, definition: BracketDefinition
    ) -> tuple[BracketRuntime, BoardScheduler, str, TournamentRoster | None]:
        snapshot = self.load(tournament_id)
        try:
            runtime_data = snapshot["runtime"]
            runtime = BracketRuntime(definition, snapshot["entrants"])
            for raw_result in runtime_data["results"]:
                game_id = raw_result["game_id"]
                match_id = "CHAMPIONSHIP" if game_id in {"GF", "GGF"} else game_id
                result = runtime.record_winner(match_id, raw_result["winner"])
                if result.loser != raw_result["loser"]:
                    raise TournamentStoreError(
                        f"Persisted loser does not match bracket result for {game_id}"
                    )

            if runtime.placements != runtime_data["placements"]:
                raise TournamentStoreError("Persisted placements do not match replayed results")
            if runtime.championship_phase.value != runtime_data["championship_phase"]:
                raise TournamentStoreError("Persisted championship phase does not match results")
            if runtime.champion != runtime_data["champion"]:
                raise TournamentStoreError("Persisted champion does not match replayed results")

            scheduler = BoardScheduler.from_snapshot(snapshot["scheduler"], runtime)
            registration_data = snapshot.get("registration")
            roster = TournamentRoster.from_dict(registration_data) if registration_data is not None else None
            if roster is not None:
                roster.validate_for_bracket(definition)
                if roster.runtime_entrants(definition) != runtime.entrants:
                    raise TournamentStoreError("Persisted roster does not match bracket entrants")
            bracket_file = snapshot["bracket_file"]
            if not isinstance(bracket_file, str) or not bracket_file:
                raise TournamentStoreError("Persisted bracket_file is invalid")
            return runtime, scheduler, bracket_file, roster
        except (KeyError, TypeError, ValueError, BracketRuntimeError, BoardSchedulerError, RegistrationError) as exc:
            if isinstance(exc, TournamentStoreError):
                raise
            raise TournamentStoreError(f"Could not restore tournament: {exc}") from exc

    def unfinished(self) -> list[dict[str, Any]]:
        """List resumable tournaments without exposing or modifying their snapshots."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT tournament_id, bracket_file, state_json, created_at, updated_at
                    FROM tournaments
                    ORDER BY updated_at DESC, created_at DESC
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise TournamentStoreError(f"Could not list tournaments: {exc}") from exc

        output = []
        for row in rows:
            try:
                snapshot = json.loads(row["state_json"])
                runtime = snapshot["runtime"]
                if runtime.get("champion") is not None:
                    continue
                results = runtime.get("results", [])
                entrants = snapshot.get("entrants", {})
                output.append({
                    "tournament_id": row["tournament_id"],
                    "bracket_file": row["bracket_file"],
                    "team_count": len(entrants),
                    "completed_matches": len(results),
                    "updated_at": row["updated_at"],
                    "dashboard_url": f"/tournaments/{row['tournament_id']}",
                })
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
                raise TournamentStoreError(
                    f"Could not read tournament listing entry {row['tournament_id']}: {exc}"
                ) from exc
        return output

    def completed(self) -> list[dict[str, Any]]:
        """Return immutable tournament snapshots whose championship is complete."""
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT tournament_id, bracket_file, state_json, created_at, updated_at
                    FROM tournaments
                    ORDER BY updated_at DESC, created_at DESC
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise TournamentStoreError(f"Could not list completed tournaments: {exc}") from exc

        output: list[dict[str, Any]] = []
        for row in rows:
            try:
                snapshot = json.loads(row["state_json"])
                runtime = snapshot.get("runtime", {})
                champion = runtime.get("champion")
                if champion is None:
                    continue
                output.append({
                    "tournament_id": row["tournament_id"],
                    "bracket_file": row["bracket_file"],
                    "created_at": row["created_at"],
                    "completed_at": row["updated_at"],
                    "snapshot": snapshot,
                })
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                raise TournamentStoreError(
                    f"Could not read completed tournament {row['tournament_id']}: {exc}"
                ) from exc
        return output

    def delete(self, tournament_id: str) -> None:
        """Permanently delete a tournament snapshot and its event history."""
        try:
            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM tournament_events WHERE tournament_id = ?",
                    (tournament_id,),
                )
                tournament = connection.execute(
                    "DELETE FROM tournaments WHERE tournament_id = ?",
                    (tournament_id,),
                )
                if tournament.rowcount == 0:
                    raise TournamentStoreError(f"Unknown tournament: {tournament_id}")
        except sqlite3.Error as exc:
            raise TournamentStoreError(f"Could not delete tournament: {exc}") from exc

    def events(self, tournament_id: str) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT event_id, event_type, payload_json, occurred_at
                    FROM tournament_events
                    WHERE tournament_id = ?
                    ORDER BY event_id
                    """,
                    (tournament_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise TournamentStoreError(f"Could not read tournament events: {exc}") from exc
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "occurred_at": row["occurred_at"],
            }
            for row in rows
        ]
