from pathlib import Path

from app.brackets.audit import audit_directory


def test_audit_reports_every_supplied_bracket_and_known_diagnostics():
    data_dir = Path(__file__).parents[1] / "data"

    report = audit_directory(data_dir)

    assert report["bracket_count"] == 7
    assert report["diagnostic_count"] == 5
    by_team_count = {item["team_count"]: item for item in report["brackets"]}
    assert by_team_count[5]["game_count"] == 9
    assert by_team_count[9]["game_count"] == 17
    assert by_team_count[5]["championship"]["logical_match"] == "Championship Match"

    five_messages = [item["message"] for item in by_team_count[5]["diagnostics"]]
    nine_messages = [item["message"] for item in by_team_count[9]["diagnostics"]]
    assert five_messages == []
    assert any("L-10" in message for message in nine_messages)
    assert any("W-G17" in message for message in nine_messages)
