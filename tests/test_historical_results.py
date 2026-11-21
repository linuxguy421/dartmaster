from fastapi.testclient import TestClient

from app import main


def completed_tournament(tmp_path, monkeypatch):
    monkeypatch.setenv("DARTMASTER_DB_PATH", str(tmp_path / "dartmaster.sqlite3"))
    client = TestClient(main.app)
    for gender in ("male", "female"):
        for index in range(4):
            player = client.post(
                "/api/registration/players",
                json={"display_name": f"{gender.title()} {index + 1}", "gender": gender},
            ).json()
            assert client.put(
                f"/api/registration/players/{player['player_id']}/payment",
                json={"paid": True},
            ).status_code == 200
    players = client.get("/api/registration").json()["players"]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 1, 2, 3, 4], strict=True)
    }
    assert client.post("/api/registration/draw", json={"mixed_draws": draws}).status_code == 200
    created = client.post("/api/tournaments", json={"bracket_file": "4teamD.json"}).json()
    tournament_id = created["tournament_id"]
    base = f"/api/tournaments/{tournament_id}/boards"

    def play(match_id, board=1):
        assigned = client.post(base + f"/{board}/assign", json={"match_id": match_id})
        assert assigned.status_code == 200
        match = assigned.json()["boards"][board - 1]["match"]
        result = client.post(
            base + f"/{board}/winner", json={"winner": match["participants"][0]}
        )
        assert result.status_code == 200
        return result.json()

    play("G1")
    play("G2", 2)
    play("G3")
    play("G4", 2)
    play("G5")
    play("CHAMPIONSHIP")
    return client, tournament_id


def test_historical_results_only_lists_completed_tournaments(tmp_path, monkeypatch):
    client, tournament_id = completed_tournament(tmp_path, monkeypatch)

    response = client.get("/api/historical-results")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["tournaments"] == 1
    assert data["summary"]["games"] == 6
    assert data["summary"]["players"] == 8
    assert len(data["tournaments"]) == 1
    assert data["tournaments"][0]["tournament_id"] == tournament_id
    assert data["tournaments"][0]["champion"]


def test_historical_results_detail_and_page(tmp_path, monkeypatch):
    client, tournament_id = completed_tournament(tmp_path, monkeypatch)

    detail = client.get(f"/api/historical-results/{tournament_id}")
    assert detail.status_code == 200
    assert len(detail.json()["tournaments"]) == 1
    assert len(detail.json()["tournaments"][0]["results"]) == 6

    page = client.get(f"/historical-results/{tournament_id}")
    assert page.status_code == 200
    assert "Historical Results" in page.text
    assert "Completed matches" in page.text


def test_unknown_historical_tournament_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv("DARTMASTER_DB_PATH", str(tmp_path / "dartmaster.sqlite3"))
    response = TestClient(main.app).get("/api/historical-results/missing")
    assert response.status_code == 404
