from fastapi.testclient import TestClient

from app import main


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("DARTMASTER_DB_PATH", str(tmp_path / "dartmaster.sqlite3"))
    return TestClient(main.app)


def add_players(client, males=2, females=2):
    for index in range(males):
        response = client.post(
            "/api/registration/players",
            json={"display_name": f"Male {index + 1}", "gender": "male"},
        )
        assert response.status_code == 201
    for index in range(females):
        response = client.post(
            "/api/registration/players",
            json={"display_name": f"Female {index + 1}", "gender": "female"},
        )
        assert response.status_code == 201


def test_registration_draw_and_roster_survive_api_reload(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client)

    players = client.get("/api/registration").json()["players"]
    draws = {
        players[0]["player_id"]: 1,
        players[1]["player_id"]: 2,
        players[2]["player_id"]: 1,
        players[3]["player_id"]: 2,
    }
    response = client.post(
        "/api/registration/draw",
        json={"mixed_draws": draws, "draw_off_draws": {}},
    )

    assert response.status_code == 200
    assert len(response.json()["teams"]) == 2
    assert response.json()["draw"]["first_gender"] == "female"

    reloaded = client.get("/api/registration").json()
    assert len(reloaded["players"]) == 4
    assert len(reloaded["teams"]) == 2
    assert reloaded["draw"]["mixed_draws"] == draws


def test_draw_off_pairings_are_persisted(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=4, females=2)
    players = client.get("/api/registration").json()["players"]
    mixed = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 1, 2], strict=True)
    }
    unmatched = [
        player["player_id"]
        for player in players
        if player["gender"] == "male" and player["player_id"] not in {
            next(p["player_id"] for p in players if p["gender"] == "female" and mixed[p["player_id"]] == mixed[player["player_id"]])
            for player in players if player["gender"] == "male"
        }
    ]
    response = client.post(
        "/api/registration/draw",
        json={
            "mixed_draws": mixed,
            "draw_off_draws": {unmatched[0]: 9, unmatched[1]: 9},
        },
    )
    assert response.status_code == 200
    assert len(response.json()["teams"]) == 3
    assert len(response.json()["draw"]["draw_off_team_ids"]) == 1


def test_seed_assignment_and_tournament_creation(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client)
    players = client.get("/api/registration").json()["players"]
    draws = {player["player_id"]: number for player, number in zip(players, [1, 2, 1, 2], strict=True)}
    assert client.post(
        "/api/registration/draw",
        json={"mixed_draws": draws},
    ).status_code == 200

    teams = client.get("/api/registration").json()["teams"]
    bracket = next(
        item for item in client.get("/api/brackets").json()
        if item["filename"] == "4teamD.json"
    )
    assignments = {f"T{index + 1}": team["team_id"] for index, team in enumerate(teams)}
    seeded = client.put(
        "/api/registration/seeds",
        json={"bracket_file": bracket["filename"], "assignments": assignments},
    )
    assert seeded.status_code == 200

    created = client.post(
        "/api/tournaments",
        json={"bracket_file": bracket["filename"], "board_count": 4, "scheduler_mode": "manual"},
    )
    assert created.status_code == 201
    assert created.json()["team_count"] == 2
    assert created.json()["scheduler_mode"] == "manual"


def test_seed_assignment_rejects_incomplete_bracket_mapping(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client)
    players = client.get("/api/registration").json()["players"]
    draws = {player["player_id"]: number for player, number in zip(players, [1, 2, 1, 2], strict=True)}
    client.post("/api/registration/draw", json={"mixed_draws": draws})
    teams = client.get("/api/registration").json()["teams"]

    response = client.put(
        "/api/registration/seeds",
        json={"bracket_file": "4teamD.json", "assignments": {"T1": teams[0]["team_id"]}},
    )
    assert response.status_code == 400
    assert "missing seeds" in response.json()["detail"]
