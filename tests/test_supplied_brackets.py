from pathlib import Path

import pytest

from app.brackets.loader import load_bracket

DATA_DIR = Path(__file__).parents[1] / "data"

EXPECTED_GAME_COUNTS = {
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
    if team_count == 4:
        # The G5 winner advances to the championship; only its loser is awarded 3rd.
        assert "placement_match" not in bracket.games["G5"]
        assert bracket.games["G5"]["winner_advances_to"] == {"game": "GF", "slot": 1}
        assert bracket.games["G5"]["loser_drops_to"] == {
            "result": "ELIMINATED", "rank": "3rd"
        }
        assert bracket.games["G4"]["loser_drops_to"] == {
            "result": "ELIMINATED", "rank": "4th"
        }
    else:
        third_place_games = [
            (game_id, game) for game_id, game in bracket.games.items()
            if game.get("display_label") == "Playing for 3rd Place"
        ]
        assert len(third_place_games) == 1
        game_id, game = third_place_games[0]
        assert game["placement_match"] == {"winner": "4th", "loser": "3rd"}
        assert game["winner_advances_to"] == {"game": "GF", "slot": 1}
        assert game["loser_drops_to"] == {"result": "ELIMINATED", "rank": "3rd"}
        prior_fourth_game = next(
            prior for prior, definition in bracket.games.items()
            if definition.get("winner_advances_to", {}).get("game") == game_id
            and definition.get("loser_drops_to", {}).get("rank") == "4th"
        )
        assert prior_fourth_game


def test_all_supplied_brackets_have_no_reference_anomalies():
    nine = load_bracket(DATA_DIR / "9teamD.json")
    assert nine.diagnostics == []

