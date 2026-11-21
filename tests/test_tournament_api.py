from fastapi.testclient import TestClient

from app import main


def setup_tournament(tmp_path, monkeypatch, bracket_file="4teamD.json", team_count=4):
    monkeypatch.setenv("DARTMASTER_DB_PATH", str(tmp_path / "dartmaster.sqlite3"))
    client = TestClient(main.app)
    for gender in ("male", "female"):
        for index in range(team_count):
            response = client.post(
                "/api/registration/players",
                json={"display_name": f"{gender.title()} {index + 1}", "gender": gender},
            )
            assert response.status_code == 201
    players = client.get("/api/registration").json()["players"]
    numbers = list(range(1, team_count + 1)) * 2
    draws = {
        player["player_id"]: number
        for player, number in zip(players, numbers, strict=True)
    }
    assert client.post(
        "/api/registration/draw", json={"mixed_draws": draws}
    ).status_code == 200
    registration = client.get("/api/registration").json()
    assert set(registration["seed_assignments"]) == {f"T{index}" for index in range(1, team_count + 1)}
    created = client.post(
        "/api/tournaments", json={"bracket_file": bracket_file}
    )
    assert created.status_code == 201
    return client, created.json()


def test_live_dashboard_exposes_four_available_boards_and_ready_matches(tmp_path, monkeypatch):
    client, tournament = setup_tournament(tmp_path, monkeypatch)
    tournament_id = tournament["tournament_id"]

    assert tournament["dashboard_url"] == f"/tournaments/{tournament_id}"
    page = client.get(tournament["dashboard_url"])
    assert page.status_code == 200
    assert "Ready to play" in page.text
    assert "Prize payouts" in page.text
    assert "side-pot-toggle" in page.text
    assert "prizes_with_side_pot" in page.text
    assert "side-pot-instructions" not in page.text
    assert "Set aside" not in page.text
    assert "Playing for" in page.text
    assert "completedPlacements" in page.text
    assert " /ea" in page.text
    bracket_page = client.get(f"/tournaments/{tournament_id}/bracket")
    assert bracket_page.status_code == 200
    assert "total payout" in bracket_page.text
    assert "currentPayouts" in bracket_page.text
    assert "data-assign" in page.text
    assert "const selectedBoards=new Map()" in page.text
    assert "selectedBoards.set(matchId,Number(select.value))" in page.text
    assert "Choose a board" in page.text
    assert "Suggested board" not in page.text
    assert "recommended_boards" not in page.text

    status = client.get(f"/api/tournaments/{tournament_id}").json()
    assert status["payouts"] == {
        "currency": "USD",
        "prizes": {"1": 18, "2": 12, "3": 10},
        "prizes_with_side_pot": {"1": 20, "2": 8, "3": 4},
        "side_pot_amount": 8,
        "side_pot_contribution_per_player": 1,
        "side_pot_contribution_per_team": 2,
    }
    third_place = next(match for match in status["bracket"] if match["match_id"] == "G5")
    assert third_place["placement_label"] == "3rd Place"
    assert third_place["placement_payouts"] == {"winner_place": "3rd", "loser_place": "4th"}
    championship = next(match for match in status["bracket"] if match["match_id"] == "CHAMPIONSHIP")
    assert championship["placement_label"] == "1st / 2nd Place"
    assert championship["placement_payouts"] == {"winner_place": "1st", "loser_place": "2nd"}
    assert len(status["boards"]) == 4
    assert all(board["status"] == "available" for board in status["boards"])
    assert all(board["enabled"] for board in status["boards"])
    assert status["scheduler"]["free_boards"] == [1, 2, 3, 4]
    assert "recommended_boards" not in status["scheduler"]
    assert [match["match_id"] for match in status["ready_matches"]] == ["G1", "G2"]
    assert all(board["match"] is None for board in status["boards"])
    assert [match["match_id"] for match in status["bracket"]] == [
        "G1", "G2", "G3", "G4", "G5", "CHAMPIONSHIP"
    ]
    first_game = next(match for match in status["bracket"] if match["match_id"] == "G1")
    assert first_game["winner_advances_to"] == {"game": "G3", "slot": 0}
    assert first_game["loser_drops_to"] == {"game": "G4", "slot": 0}


def test_operator_assigns_ready_matches_and_completion_does_not_auto_assign(tmp_path, monkeypatch):
    client, tournament = setup_tournament(tmp_path, monkeypatch)
    tournament_id = tournament["tournament_id"]
    base = f"/api/tournaments/{tournament_id}/boards"

    assigned = client.post(base + "/3/assign", json={"match_id": "G2"})
    assert assigned.status_code == 200
    assert assigned.json()["boards"][2]["match"]["match_id"] == "G2"

    assigned = client.post(base + "/1/assign", json={"match_id": "G1"})
    assert assigned.status_code == 200
    participants = assigned.json()["boards"][0]["match"]["participants"]

    invalid = client.post(base + "/1/winner", json={"winner": "Not a team"})
    assert invalid.status_code == 409

    completed = client.post(base + "/1/winner", json={"winner": participants[0]})
    assert completed.status_code == 200
    assert completed.json()["boards"][0]["match"] is None
    assert completed.json()["boards"][2]["match"]["match_id"] == "G2"

    second = completed.json()["boards"][2]["match"]["participants"]
    completed = client.post(base + "/3/winner", json={"winner": second[0]})
    assert completed.status_code == 200
    assert completed.json()["boards"][2]["match"] is None
    assert [match["match_id"] for match in completed.json()["ready_matches"]] == ["G3", "G4"]
    assert "recommended_boards" not in completed.json()["scheduler"]


def test_assignment_rejects_unready_or_duplicate_board_matches(tmp_path, monkeypatch):
    client, tournament = setup_tournament(tmp_path, monkeypatch)
    base = f"/api/tournaments/{tournament['tournament_id']}/boards"

    not_ready = client.post(base + "/1/assign", json={"match_id": "G3"})
    assert not_ready.status_code == 409

    client.post(base + "/1/assign", json={"match_id": "G1"})
    occupied = client.post(base + "/1/assign", json={"match_id": "G2"})
    assert occupied.status_code == 409


def test_health_endpoint():
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}



def test_completed_third_place_match_exposes_prize_placement(tmp_path, monkeypatch):
    client, tournament = setup_tournament(tmp_path, monkeypatch)
    base = f"/api/tournaments/{tournament['tournament_id']}/boards"

    def play(match_id, board_id):
        assigned = client.post(base + f"/{board_id}/assign", json={"match_id": match_id})
        assert assigned.status_code == 200
        match = assigned.json()["boards"][board_id - 1]["match"]
        completed = client.post(
            base + f"/{board_id}/winner", json={"winner": match["participants"][0]}
        )
        assert completed.status_code == 200
        return completed.json()

    play("G1", 1)
    status = play("G2", 2)
    assert {match["match_id"] for match in status["ready_matches"]} == {"G3", "G4"}
    play("G3", 1)
    status = play("G4", 2)
    assert any(match["match_id"] == "G5" for match in status["ready_matches"])
    status = play("G5", 1)

    third_place = next(match for match in status["bracket"] if match["match_id"] == "G5")
    assert third_place["status"] == "completed"
    assert third_place["placement_payouts"] == {"winner_place": "3rd", "loser_place": "4th"}
    assert set(third_place["placement_players"]) == {"3rd", "4th"}
    assert all(" / " in players for players in third_place["placement_players"].values())
    assert all(
        player.startswith(("Male ", "Female "))
        for players in third_place["placement_players"].values()
        for player in players.split(" / ")
    )
    assert third_place["winner"] is not None
    assert status["placements"]["3rd"] == third_place["placement_players"]["3rd"]
    assert status["placements"]["4th"] == third_place["placement_players"]["4th"]

    championship = play("CHAMPIONSHIP", 1)
    assert championship["complete"] is True
    final_match = next(
        match for match in championship["bracket"] if match["match_id"] == "CHAMPIONSHIP"
    )
    assert championship["placements"]["1st"] == final_match["placement_players"]["1st"]
    assert championship["placements"]["2nd"] == final_match["placement_players"]["2nd"]

