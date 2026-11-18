from pathlib import Path

import pytest

from app.brackets.loader import load_bracket
from app.brackets.runtime import (
    BracketRuntime,
    BracketRuntimeError,
    ChampionshipPhase,
    GameResult,
)

DATA_DIR = Path(__file__).parents[1] / "data"


def four_team_runtime():
    definition = load_bracket(DATA_DIR / "4teamD.json")
    entrants = {"T1": "Team One", "T2": "Team Two", "T3": "Team Three", "T4": "Team Four"}
    return BracketRuntime(definition, entrants)


def advance_four_team_bracket_to_championship(runtime):
    initial = runtime.ready_matches()
    assert [match.match_id for match in initial] == ["G1", "G2"]

    runtime.record_winner("G1", "Team One")
    runtime.record_winner("G2", "Team Two")
    assert [match.match_id for match in runtime.ready_matches()] == ["G3", "G4"]

    runtime.record_winner("G3", "Team One")
    runtime.record_winner("G4", "Team Four")
    assert [match.match_id for match in runtime.ready_matches()] == ["G5"]

    runtime.record_winner("G5", "Team Four")
    championship = runtime.ready_matches()
    assert len(championship) == 1
    assert championship[0].match_id == "CHAMPIONSHIP"
    assert championship[0].source_game_id == "GF"
    assert championship[0].participants == ("Team One", "Team Four")


def test_ready_matches_follow_json_order_and_dependencies():
    runtime = four_team_runtime()

    ready = runtime.ready_matches()

    assert [match.match_id for match in ready] == ["G1", "G2"]
    assert all(match.source_game_id != "GGF" for match in ready)


def test_upper_bracket_finalist_winning_ends_championship_without_reset():
    runtime = four_team_runtime()
    advance_four_team_bracket_to_championship(runtime)

    runtime.record_winner("CHAMPIONSHIP", "Team One")

    assert runtime.champion == "Team One"
    assert runtime.championship_phase == ChampionshipPhase.COMPLETE
    assert runtime.ready_matches() == ()
    assert runtime.placements["2nd"] == "Team Four"
    assert "GGF" not in runtime.results


def test_lower_bracket_finalist_activates_reset_in_same_logical_match():
    runtime = four_team_runtime()
    advance_four_team_bracket_to_championship(runtime)

    runtime.record_winner("CHAMPIONSHIP", "Team Four")

    reset_matches = runtime.ready_matches()
    assert len(reset_matches) == 1
    reset = reset_matches[0]
    assert reset.match_id == "CHAMPIONSHIP"
    assert reset.source_game_id == "GGF"
    assert reset.phase == ChampionshipPhase.RESET
    assert reset.participants == ("Team Four", "Team One")

    runtime.record_winner("CHAMPIONSHIP", "Team One")

    assert runtime.champion == "Team One"
    assert runtime.championship_phase == ChampionshipPhase.COMPLETE
    assert runtime.ready_matches() == ()


def test_conditional_reset_cannot_be_recorded_as_separate_match():
    runtime = four_team_runtime()
    advance_four_team_bracket_to_championship(runtime)

    with pytest.raises(BracketRuntimeError, match="not a schedulable match"):
        runtime.record_winner("GGF", "Team One")


def test_winner_must_be_one_of_the_resolved_participants():
    runtime = four_team_runtime()

    with pytest.raises(BracketRuntimeError, match="not a participant"):
        runtime.record_winner("G1", "Not Playing")



def test_five_team_championship_reset_resolves_finalists():
    definition = load_bracket(DATA_DIR / "5teamD.json")
    entrants = {f"T{seed}": f"Team {seed}" for seed in range(1, 6)}
    runtime = BracketRuntime(definition, entrants)

    runtime.record_winner("G1", "Team 4")
    runtime.record_winner("G2", "Team 2")
    runtime.record_winner("G3", "Team 1")
    runtime.record_winner("G4", "Team 5")
    runtime.record_winner("G5", "Team 2")
    runtime.record_winner("G6", "Team 5")
    runtime.record_winner("G7", "Team 5")
    runtime.record_winner("CHAMPIONSHIP", "Team 5")

    reset_matches = runtime.ready_matches()

    assert len(reset_matches) == 1
    assert reset_matches[0].match_id == "CHAMPIONSHIP"
    assert reset_matches[0].source_game_id == "GGF"
    assert reset_matches[0].participants == ("Team 5", "Team 2")
