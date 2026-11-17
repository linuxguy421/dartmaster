# Dartmaster

A locally hosted Python web application for managing double-elimination darts tournaments.

## Design decisions

- FastAPI backend with a browser-based operator and display interface.
- Four dartboards can run matches concurrently, with manual board selection by default or automatic allocation.
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

## Current implementation

The foundation includes the FastAPI entrypoint, ordered JSON bracket loader, read-only bracket audit CLI, an in-memory progression engine, a four-board scheduler, and a SQLite-backed tournament session/state store. The engine resolves entrant and winner/loser references, returns ready matches in source insertion order, validates winner submissions, and models `GF`/`GGF` as one logical Championship Match. The scheduler defaults to manual mode (the operator enables boards) and also supports auto mode (all configured boards are eligible). Use `TournamentSession.create(...)` to start a persisted tournament and `TournamentSession.restore(...)` to recover it after restart. Operator actions and match results are snapshotted transactionally alongside an append-only event history. See [Tournament match model](docs/tournament-model.md) and [Bracket audit](docs/bracket-audit.md).

Run the audit with:

```bash
python -m app.brackets.audit
```

The application must not generate a replacement bracket topology or reorder the JSON-defined games. A required championship reset remains part of the same logical match and must retain its board assignment. Known source anomalies are reported and never silently repaired.
