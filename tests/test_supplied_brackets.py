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
    assert bracket.currency == "USD"
    assert bracket.games["GF"]["placement_match"] == {"winner": "1st", "loser": "2nd"}
    assert bracket.games["GGF"]["placement_match"] == {"winner": "1st", "loser": "2nd"}
    third_place = [
        game for game in bracket.games.values()
        if game.get("placement_match") == {"winner": "3rd", "loser": "4th"}
    ]
    assert len(third_place) == 1


def test_known_legacy_reference_anomalies_are_reported():
    five = load_bracket(DATA_DIR / "5teamD.json")
    nine = load_bracket(DATA_DIR / "9teamD.json")

    five_messages = [item.message for item in five.diagnostics]
    nine_messages = [item.message for item in nine.diagnostics]

    assert five_messages == []
    assert any("L-10" in message and "missing game 10" in message for message in nine_messages)
    assert any("W-G17" in message and "missing game G17" in message for message in nine_messages)
    assert any("instead of L-G10" in message for message in nine_messages)
    assert any("instead of W-G13" in message for message in nine_messages)
    assert any("instead of W-G15" in message for message in nine_messages)


@pytest.mark.parametrize("team_count", [3, 4, 6, 7, 8, 10])
def test_valid_championship_reset_references(team_count):
    bracket = load_bracket(DATA_DIR / f"{team_count}teamD.json")

    assert bracket.games["GGF"]["teams"] == ["W-GF", "L-GF"]
    assert bracket.games["GF"]["winner_advances_to"] == {"result": "CHAMPION"}
    assert bracket.games["GF"]["loser_drops_to"] == {"result": "GF_CONDITIONAL"}


SIDE_POT_PAYOUTS = {
    3: ({"1": 24, "2": 0, "3": 0}, 6),
    4: ({"1": 20, "2": 8, "3": 4}, 8),
    5: ({"1": 24, "2": 10, "3": 6}, 10),
    6: ({"1": 28, "2": 12, "3": 8}, 12),
    7: ({"1": 32, "2": 14, "3": 10}, 14),
    8: ({"1": 34, "2": 18, "3": 12}, 16),
    9: ({"1": 38, "2": 20, "3": 14}, 18),
    10: ({"1": 42, "2": 22, "3": 16}, 20),
}


@pytest.mark.parametrize(("team_count", "expected"), SIDE_POT_PAYOUTS.items())
def test_supplied_bracket_has_spreadsheet_side_pot_payouts(team_count, expected):
    bracket = load_bracket(DATA_DIR / f"{team_count}teamD.json")

    assert bracket.prizes_with_side_pot == expected[0]
    assert bracket.side_pot_amount == expected[1]
    assert bracket.side_pot_contribution_per_player == 1
    assert bracket.side_pot_amount == team_count * 2
