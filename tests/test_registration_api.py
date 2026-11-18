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


def test_draw_rejects_odd_number_of_registered_players(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=2, females=1)
    players = client.get("/api/registration").json()["players"]

    response = client.post(
        "/api/registration/draw",
        json={
            "mixed_draws": {
                player["player_id"]: index + 1
                for index, player in enumerate(players)
            }
        },
    )

    assert response.status_code == 400
    assert "even number of players" in response.json()["detail"]
    registration = client.get("/api/registration").json()
    assert registration["teams"] == []
    assert registration["draw"] is None


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


def test_exactly_two_unmatched_players_automatically_become_partners(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=6, females=4)
    players = client.get("/api/registration").json()["players"]
    mixed = {
        player["player_id"]: number
        for player, number in zip(
            players, [4, 2, 1, 3, 6, 5, 1, 4, 2, 3], strict=True
        )
    }

    response = client.post(
        "/api/registration/draw",
        json={"mixed_draws": mixed},
    )

    assert response.status_code == 200
    teams = response.json()["teams"]
    assert len(teams) == 5
    unmatched_team = next(
        team for team in teams
        if {team["player_one"], team["player_two"]} == {"Male 5", "Male 6"}
    )
    assert unmatched_team["player_one"] != unmatched_team["player_two"]
    assert len(response.json()["draw"]["draw_off_team_ids"]) == 1


def test_draw_off_pairings_are_persisted(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=6, females=2)
    players = client.get("/api/registration").json()["players"]
    mixed = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 5, 6, 1, 2], strict=True)
    }
    female_numbers = {
        mixed[player["player_id"]]
        for player in players
        if player["gender"] == "female"
    }
    unmatched = [
        player["player_id"]
        for player in players
        if player["gender"] == "male"
        and mixed[player["player_id"]] not in female_numbers
    ]
    response = client.post(
        "/api/registration/draw",
        json={
            "mixed_draws": mixed,
            "draw_off_draws": {unmatched[0]: 9, unmatched[1]: 9, unmatched[2]: 10, unmatched[3]: 10},
        },
    )
    assert response.status_code == 200
    assert len(response.json()["teams"]) == 4
    assert len(response.json()["draw"]["draw_off_team_ids"]) == 2


def test_seed_assignment_and_tournament_creation(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=4, females=4)
    players = client.get("/api/registration").json()["players"]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 1, 2, 3, 4], strict=True)
    }
    assert client.post(
        "/api/registration/draw",
        json={"mixed_draws": draws},
    ).status_code == 200

    registration = client.get("/api/registration").json()
    teams = registration["teams"]
    assert set(registration["seed_assignments"]) == {"T1", "T2", "T3", "T4"}

    created = client.post(
        "/api/tournaments",
        json={"bracket_file": bracket["filename"]},
    )
    assert created.status_code == 201
    assert created.json()["team_count"] == 4
    assert created.json()["board_count"] == 4
    assert created.json()["dashboard_url"] == f"/tournaments/{created.json()['tournament_id']}"

    tournament = client.get(created.json()["dashboard_url"]).status_code
    assert tournament == 200
    state = client.get(f"/api/tournaments/{created.json()['tournament_id']}").json()
    expected_entrants = {
        f"{team['player_one']} & {team['player_two']}"
        for team in teams
    }
    actual_entrants = {
        participant
        for match in state["bracket"]
        if match["status"] == "ready"
        for participant in match["participants"]
    }
    assert actual_entrants == expected_entrants
    assert all("Team " not in entrant for entrant in actual_entrants)


def test_teams_receive_automatic_seeds_in_original_draw_order(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=6, females=4)
    players = client.get("/api/registration").json()["players"]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, [4, 2, 1, 3, 6, 5, 1, 4, 2, 3], strict=True)
    }
    response = client.post("/api/registration/draw", json={"mixed_draws": draws})
    assert response.status_code == 200

    registration = response.json()
    seeds = registration["seed_assignments"]
    assert set(seeds) == {"T1", "T2", "T3", "T4", "T5"}
    team_by_id = {team["team_id"]: team for team in registration["teams"]}
    seeded_teams = [
        team_by_id[seeds[f"T{index}"]] for index in range(1, 6)
    ]
    assert [(team["player_one"], team["player_two"]) for team in seeded_teams[:4]] == [
        ("Male 3", "Female 1"),
        ("Male 2", "Female 3"),
        ("Male 4", "Female 4"),
        ("Male 1", "Female 2"),
    ]
    assert set((seeded_teams[4]["player_one"], seeded_teams[4]["player_two"])) == {
        "Male 5", "Male 6"
    }


def test_registration_page_auto_selects_bracket_by_team_count(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    response = client.get("/")

    assert response.status_code == 200
    assert 'Bracket selected automatically' in response.text
    assert "brackets.find(b=>b.team_count===state.teams.length)" in response.text
    assert 'id="bracket-select" disabled' in response.text
    assert "window.location.assign(result.dashboard_url)" in response.text


def test_registration_starts_blank_and_unfinished_tournament_can_be_resumed(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=4, females=4)
    players = client.get("/api/registration").json()["players"]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 1, 2, 3, 4], strict=True)
    }
    assert client.post("/api/registration/draw", json={"mixed_draws": draws}).status_code == 200
    registration = client.get("/api/registration").json()
    assert len(registration["seed_assignments"]) == 4

    created = client.post("/api/tournaments", json={"bracket_file": "4teamD.json"})
    assert created.status_code == 201
    tournament_id = created.json()["tournament_id"]

    fresh_registration = client.get("/api/registration").json()
    assert fresh_registration["players"] == []
    assert fresh_registration["teams"] == []
    assert fresh_registration["seed_assignments"] == {}

    unfinished = client.get("/api/tournaments").json()
    assert len(unfinished) == 1
    assert unfinished[0]["tournament_id"] == tournament_id
    assert unfinished[0]["dashboard_url"] == f"/tournaments/{tournament_id}"
    assert client.get(unfinished[0]["dashboard_url"]).status_code == 200
    assert client.get("/").status_code == 200
    assert "Resume an unfinished tournament" in client.get("/").text


def test_completed_tournaments_are_not_listed_as_unfinished(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=4, females=4)
    players = client.get("/api/registration").json()["players"]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 1, 2, 3, 4], strict=True)
    }
    client.post("/api/registration/draw", json={"mixed_draws": draws})
    registration = client.get("/api/registration").json()
    assert len(registration["seed_assignments"]) == 4
    created = client.post("/api/tournaments", json={"bracket_file": "4teamD.json"}).json()
    tournament_id = created["tournament_id"]
    base = f"/api/tournaments/{tournament_id}/boards"

    # Complete the 4-team bracket using explicit board assignments and winner declarations.
    for match_id in ("G1", "G2"):
        ready = client.get(f"/api/tournaments/{tournament_id}").json()["ready_matches"]
        match = next(item for item in ready if item["match_id"] == match_id)
        board = 1 if match_id == "G1" else 2
        assert client.post(f"{base}/{board}/assign", json={"match_id": match_id}).status_code == 200
        assert client.post(f"{base}/{board}/winner", json={"winner": match["participants"][0]}).status_code == 200
    for match_id in ("G3", "G4"):
        ready = client.get(f"/api/tournaments/{tournament_id}").json()["ready_matches"]
        match = next(item for item in ready if item["match_id"] == match_id)
        board = 1 if match_id == "G3" else 2
        assert client.post(f"{base}/{board}/assign", json={"match_id": match_id}).status_code == 200
        assert client.post(f"{base}/{board}/winner", json={"winner": match["participants"][0]}).status_code == 200
    state = client.get(f"/api/tournaments/{tournament_id}").json()
    final = next(item for item in state["ready_matches"] if item["match_id"] == "G5")
    assert client.post(f"{base}/1/assign", json={"match_id": "G5"}).status_code == 200
    assert client.post(f"{base}/1/winner", json={"winner": final["participants"][0]}).status_code == 200
    championship = client.get(f"/api/tournaments/{tournament_id}").json()["ready_matches"]
    assert [item["match_id"] for item in championship] == ["CHAMPIONSHIP"]
    assert client.post(f"{base}/1/assign", json={"match_id": "CHAMPIONSHIP"}).status_code == 200
    final_match = client.get(f"/api/tournaments/{tournament_id}").json()["boards"][0]["match"]
    assert client.post(
        f"{base}/1/winner", json={"winner": final_match["participants"][0]}
    ).status_code == 200
    assert client.get("/api/tournaments").json() == []


def test_unfinished_tournament_can_be_permanently_deleted(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    add_players(client, males=4, females=4)
    players = client.get("/api/registration").json()["players"]
    draws = {
        player["player_id"]: number
        for player, number in zip(players, [1, 2, 3, 4, 1, 2, 3, 4], strict=True)
    }
    assert client.post("/api/registration/draw", json={"mixed_draws": draws}).status_code == 200
    registration = client.get("/api/registration").json()
    assert len(registration["seed_assignments"]) == 4
    created = client.post("/api/tournaments", json={"bracket_file": "4teamD.json"})
    assert created.status_code == 201
    tournament_id = created.json()["tournament_id"]

    assert client.get(f"/api/tournaments/{tournament_id}").status_code == 200
    assert client.delete(f"/api/tournaments/{tournament_id}").status_code == 204
    assert client.get(f"/api/tournaments/{tournament_id}").status_code == 404
    assert client.get("/api/tournaments").json() == []
    assert client.delete(f"/api/tournaments/{tournament_id}").status_code == 404


def test_registration_page_offers_confirmed_permanent_tournament_deletion(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    response = client.get("/")
    assert response.status_code == 200
    assert "data-delete-tournament" in response.text
    assert "Permanently delete this tournament and all of its saved match/event history? This cannot be undone." in response.text
