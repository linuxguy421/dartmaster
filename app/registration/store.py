from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.registration.roster import RegistrationError, TournamentRoster


class RegistrationDraftStore:
    """Persist the active pre-tournament roster and recorded draw in SQLite."""

    DRAFT_ID = "active"

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS registration_drafts (
                    draft_id TEXT PRIMARY KEY,
                    roster_json TEXT NOT NULL,
                    draw_json TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def load(self) -> tuple[TournamentRoster, dict[str, Any] | None]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT roster_json, draw_json FROM registration_drafts WHERE draft_id = ?",
                (self.DRAFT_ID,),
            ).fetchone()
        if row is None:
            return TournamentRoster(), None
        try:
            roster = TournamentRoster.from_dict(json.loads(row[0]))
            draw_state = json.loads(row[1]) if row[1] is not None else None
        except (json.JSONDecodeError, RegistrationError, TypeError) as exc:
            raise RegistrationError(f"Could not load registration draft: {exc}") from exc
        if draw_state is not None and not isinstance(draw_state, dict):
            raise RegistrationError("Persisted draw state must be an object")
        return roster, draw_state

    def save(
        self,
        roster: TournamentRoster,
        draw_state: dict[str, Any] | None,
    ) -> None:
        roster_json = json.dumps(roster.to_dict(), separators=(",", ":"))
        draw_json = (
            json.dumps(draw_state, separators=(",", ":"))
            if draw_state is not None
            else None
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO registration_drafts (
                    draft_id, roster_json, draw_json, updated_at
                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(draft_id) DO UPDATE SET
                    roster_json = excluded.roster_json,
                    draw_json = excluded.draw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.DRAFT_ID, roster_json, draw_json),
            )
