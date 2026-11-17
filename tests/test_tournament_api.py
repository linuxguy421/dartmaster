from fastapi.testclient import TestClient

from app import main


def setup_tournament(tmp_path, monkeypatch, mode="manual", board_count=4):
    monkeypatch.setenv("DARTMASTER_DB_PATH", str(tmp_path / "dartmaster.sqlite3"))
    client = TestClient(main.app)
    for gender in ("male", "female"):
        for index in range(4):
            response = client.post(
                "/api/registration/players",
                json={"display_name": f"{gender.title()} {index + 1}", "gender": gender},
            )
            assert response.status_code == 201
    players = client.get("/api/registration").json()["players"]
    numbers = [1, 2, 3, 4, 1, 2, 3, 4]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, numbers, strict=True)
    }
    assert client.post(
        "/api/registration/draw", json={"mixed_draws": draws}
    ).status_code == 200
    teams = client.get("/api/registration").json()["teams"]
    assignments = {
        f"T{index + 1}": team["team_id"]
        for index, team in enumerate(teams)
    }
    assert client.put(
        "/api/registration/seeds",
        json={"bracket_file": "4teamD.json", "assignments": assignments},
    ).status_code == 200
    created = client.post(
        "/api/tournaments",
        json={
            "bracket_file": "4teamD.json",
            "board_count": board_count,
            "scheduler_mode": mode,
        },
    )
    assert created.status_code == 201
    return client, created.json()


def test_live_dashboard_exposes_four_boards_and_manual_enable(tmp_path, monkeypatch):
    client, tournament = setup_tournament(tmp_path, monkeypatch)
    tournament_id = tournament["tournament_id"]

    assert tournament["dashboard_url"] == f"/tournaments/{tournament_id}"
    page = client.get(tournament["dashboard_url"])
    assert page.status_code == 200
    assert "Live tournament control" in page.text

    status = client.get(f"/api/tournaments/{tournament_id}").json()
    assert len(status["boards"]) == 4
    assert all(board["status"] == "disabled" for board in status["boards"])
    assert status["scheduler"]["mode"] == "manual"

    enabled = client.post(
        f"/api/tournaments/{tournament_id}/boards/2/enable"
    )
    assert enabled.status_code == 200
    assert enabled.json()["boards"][1]["match"]["match_id"] == "G1"
    assert enabled.json()["boards"][1]["status"] == "in_progress"


def test_board_winner_refills_enabled_board_and_rejects_nonparticipant(tmp_path, monkeypatch):
    client, tournament = setup_tournament(tmp_path, monkeypatch)
    tournament_id = tournament["tournament_id"]
    base = f"/api/tournaments/{tournament_id}/boards/1"
    client.post(base + "/enable")
    state = client.get(f"/api/tournaments/{tournament_id}").json()
    participants = state["boards"][0]["match"]["participants"]

    invalid = client.post(base + "/winner", json={"winner": "Not a team"})
    assert invalid.status_code == 409

    completed = client.post(base + "/winner", json={"winner": participants[0]})
    assert completed.status_code == 200
    assert completed.json()["boards"][0]["match"] is None
    assert completed.json()["results"][0]["winner"] == participants[0]


def test_auto_mode_fills_all_ready_matches_and_can_switch_to_manual(tmp_path, monkeypatch):
    client, tournament = setup_tournament(
        tmp_path, monkeypatch, mode="auto", board_count=2
    )
    tournament_id = tournament["tournament_id"]
    status = client.get(f"/api/tournaments/{tournament_id}").json()
    assert [board["match"]["match_id"] for board in status["boards"][:2]] == [
        "G1", "G2"
    ]
    assert status["boards"][2]["status"] == "unavailable"

    changed = client.put(
        f"/api/tournaments/{tournament_id}/scheduler",
        json={"mode": "manual"},
    )
    assert changed.status_code == 200
    assert changed.json()["scheduler"]["mode"] == "manual"
    assert changed.json()["scheduler"]["enabled_boards"] == [1, 2]
