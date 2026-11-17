# Dartmaster

A locally hosted Python web application for managing double-elimination darts tournaments.

## Design decisions

- FastAPI backend with a browser-based operator and display interface.
- Four dartboards can run matches concurrently.
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

The initial foundation includes the FastAPI entrypoint, Python project configuration, and ordered JSON bracket loader. The next milestone is comprehensive validation and tests against every supplied bracket file, followed by the tournament progression engine.

The application must not generate a replacement bracket topology or reorder the JSON-defined games. The `GF` and conditional `GGF` source nodes are presented and scheduled as one logical Championship Match; a required reset stays on the same board and is never queued as a separate match. See [Tournament match model](docs/tournament-model.md).
