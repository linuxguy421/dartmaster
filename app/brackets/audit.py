from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.brackets.loader import available_brackets, load_bracket


def audit_directory(directory: str | Path) -> dict[str, Any]:
    """Return a machine-readable audit without modifying any source bracket."""
    reports: list[dict[str, Any]] = []

    for path in available_brackets(directory):
        bracket = load_bracket(path)
        team_count = int(path.name.split("team")[0])
        reports.append(
            {
                "file": path.name,
                "team_count": team_count,
                "game_count": len(bracket.games),
                "game_order": list(bracket.game_order),
                "championship": {
                    "first_final": "GF",
                    "conditional_reset": "GGF",
                    "logical_match": "Championship Match",
                    "reset_source_participants": bracket.games.get("GGF", {}).get("teams"),
                },
                "diagnostics": [
                    {"game_id": item.game_id, "message": item.message}
                    for item in bracket.diagnostics
                ],
            }
        )

    return {
        "bracket_count": len(reports),
        "diagnostic_count": sum(len(item["diagnostics"]) for item in reports),
        "brackets": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit supplied Dartmaster bracket JSON files without changing them."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path(__file__).parents[2] / "data",
        help="directory containing *teamD.json bracket files",
    )
    args = parser.parse_args()
    print(json.dumps(audit_directory(args.directory), indent=2))


if __name__ == "__main__":
    main()
