# Dartmaster

A locally hosted Python web application for managing double-elimination darts tournaments.

## Design decisions

- FastAPI backend with a browser-based operator and display interface.
- Four dartboards are always available. The operator explicitly assigns bracket-ready matches to boards; no match is auto-assigned.
- Match results are winner-only; Dartmaster does not track dart scores.
- Existing JSON bracket files in `data/` are authoritative. Their game insertion order and routing are preserved.
- Bracket loading reports structural/reference anomalies without silently repairing source files.
- Tournament rules and state management remain independent of the web interface.

## Development

Python 3.12 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

By default, registration drafts and tournament state are stored in `data/dartmaster.sqlite3`.
Set `DARTMASTER_DB_PATH` to use a different SQLite database location.


## Docker Compose deployment

Docker Compose runs Dartmaster as a single application container. The supplied bracket JSON files remain in the image under /app/data; only the SQLite database is stored in the persistent dartmaster-data named volume.

```bash
cp .env.example .env
docker compose up -d --build
```

Open http://localhost:8000 (or the host port configured by DARTMASTER_PORT in .env). The container exposes a health check at /health.

Useful operations:

```bash
docker compose logs -f dartmaster
docker compose ps
docker compose restart dartmaster
docker compose up -d --build
docker compose down
```

Stopping the stack with docker compose down preserves tournament and registration data. **Do not use docker compose down -v** unless you intentionally want to delete the dartmaster-data volume and all persisted data. Back up that volume before replacing the host or performing storage maintenance.

## Current implementation

The foundation includes the ordered JSON bracket loader, read-only bracket audit CLI, in-memory progression engine, operator-controlled four-board assignment system, SQLite-backed tournament session/state store, and player/team registration domain. The browser setup workflow is served at `/`. Starting a tournament opens its live four-board dashboard at `/tournaments/{tournament_id}`, with polling updates, a bracket-driven ready-match queue, explicit board assignment, winner-only match completion, and a completed-match history:

1. Register players with a display name and gender.
2. Record the larger group's number draw first (females draw first when group sizes are equal), then the other group's matching numbers.
3. Record a draw-off number for every unmatched player; each draw-off number must occur exactly twice to identify a partner.
4. Review the generated mixed and same-gender teams.
5. Dartmaster automatically selects the JSON bracket matching the generated team count; assign each team to a seed and start the tournament.\n6. Use the live dashboard to review matches unlocked by the JSON bracket, assign each match to any free board, record winners, and monitor progression. All four boards are always available.

The registration draft, recorded draw numbers, teams, and seed assignments persist in SQLite. Starting a tournament snapshots the validated roster alongside bracket progression and scheduler state. The tournament engine resolves entrant and winner/loser references, returns ready matches in source insertion order, validates winner submissions, and models `GF`/`GGF` as one logical Championship Match. The board scheduler never assigns matches automatically. It recommends a spread-out board selection based on the number of ready matches (preferring boards 1/3, then 2/4), but the operator makes every assignment. Completing a match frees its board; newly unlocked matches return to the ready queue for operator selection.

Use `TournamentSession.create(...)` to create a persisted tournament and `TournamentSession.restore(...)` to recover it after restart. Operator actions and match results are snapshotted transactionally alongside an append-only event history. See [Tournament match model](docs/tournament-model.md) and [Bracket audit](docs/bracket-audit.md).

Run the audit with:

```bash
python -m app.brackets.audit
```

The application must not generate a replacement bracket topology or reorder the JSON-defined games. A required championship reset remains part of the same logical match and must retain its board assignment. Known source anomalies are reported and never silently repaired.
