import json

from app.brackets.loader import load_bracket


def test_loader_preserves_json_game_order(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"games": {
        "G2": {"teams": ["T1", "T2"]},
        "G1": {"teams": ["T3", "T4"]},
    }}), encoding="utf-8")

    bracket = load_bracket(path)

    assert bracket.game_order == ("G2", "G1")


def test_loader_reports_bad_references_without_rewriting_source(tmp_path):
    path = tmp_path / "legacy.json"
    payload = {"games": {
        "GF": {
            "teams": ["W-G99", "W-GF"],
            "winner_advances_to": {"result": "CHAMPION"},
            "loser_drops_to": {"result": "GF_CONDITIONAL"},
        }
    }}
    original = json.dumps(payload)
    path.write_text(original, encoding="utf-8")

    bracket = load_bracket(path)

    assert bracket.games == payload["games"]
    assert any("missing game G99" in item.message for item in bracket.diagnostics)
    assert path.read_text(encoding="utf-8") == original



def test_loader_reports_route_and_destination_slot_disagreement(tmp_path):
    path = tmp_path / "misrouted.json"
    payload = {
        "games": {
            "G1": {
                "teams": ["T1", "T2"],
                "winner_advances_to": {"game": "G2", "slot": 0},
                "loser_drops_to": {"result": "ELIMINATED", "rank": "2nd"},
            },
            "G2": {
                "teams": ["T3", "W-G1"],
                "winner_advances_to": {"result": "CHAMPION"},
                "loser_drops_to": {"result": "ELIMINATED", "rank": "1st"},
            },
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    bracket = load_bracket(path)

    assert any(
        "points to G2[0]" in item.message and "instead of W-G1" in item.message
        for item in bracket.diagnostics
    )
