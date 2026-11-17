from pathlib import Path

import pytest

from app.brackets.loader import load_bracket

DATA_DIR = Path(__file__).parents[1] / "data"

EXPECTED_GAME_COUNTS = {
    3: 5,
    4: 7,
    5: 9,
    6: 11,
    7: 13,
    8: 15,
    9: 17,
    10: 19,
}


@pytest.mark.parametrize(("team_count", "game_count"), EXPECTED_GAME_COUNTS.items())
def test_supplied_bracket_preserves_all_source_games(team_count, game_count):
    path = DATA_DIR / f"{team_count}teamD.json"

    bracket = load_bracket(path)

    assert len(bracket.games) == game_count
    assert bracket.game_order[0] == "G1"
    assert bracket.game_order[-2:] == ("GF", "GGF")


def test_known_legacy_reference_anomalies_are_reported():
    five = load_bracket(DATA_DIR / "5teamD.json")
    nine = load_bracket(DATA_DIR / "9teamD.json")

    five_messages = [item.message for item in five.diagnostics]
    nine_messages = [item.message for item in nine.diagnostics]

    assert any("W-G8" in message and "missing game G8" in message for message in five_messages)
    assert any("L-G8" in message and "missing game G8" in message for message in five_messages)
    assert any("L-10" in message and "missing game 10" in message for message in nine_messages)
    assert any("W-G17" in message and "missing game G17" in message for message in nine_messages)


@pytest.mark.parametrize("team_count", [3, 4, 6, 7, 8, 10])
def test_valid_championship_reset_references(team_count):
    bracket = load_bracket(DATA_DIR / f"{team_count}teamD.json")

    assert bracket.games["GGF"]["teams"] == ["W-GF", "L-GF"]
    assert bracket.games["GF"]["winner_advances_to"] == {"result": "CHAMPION"}
    assert bracket.games["GF"]["loser_drops_to"] == {"result": "GF_CONDITIONAL"}
