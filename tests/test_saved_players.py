from fastapi.testclient import TestClient

from app import main


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("DARTMASTER_DB_PATH",str(tmp_path/"dartmaster.sqlite3"))
    return TestClient(main.app)

def test_saved_player_crud_and_duplicate_detection(tmp_path,monkeypatch):
    client=client_for(tmp_path,monkeypatch)
    created=client.post("/api/saved-players",json={"display_name":"Alex","gender":"male"})
    assert created.status_code==201
    pid=created.json()["player_id"]
    duplicate=client.post("/api/saved-players",json={"display_name":" alex ","gender":"female"})
    assert duplicate.status_code==400
    updated=client.put(f"/api/saved-players/{pid}",json={"display_name":"Alex Updated","gender":"female","active":False})
    assert updated.status_code==200
    assert updated.json()["active"] is False
    assert client.get("/api/saved-players?active_only=true").json()==[]
    assert client.get("/api/saved-players").json()[0]["display_name"]=="Alex Updated"
    assert client.delete(f"/api/saved-players/{pid}").status_code==204
    assert client.get("/api/saved-players").json()==[]

def test_setup_page_and_registration_links(tmp_path,monkeypatch):
    client=client_for(tmp_path,monkeypatch)
    assert client.get("/setup").status_code==200
    page=client.get("/")
    assert page.status_code==200
    assert "Add from saved roster" in page.text
    assert "Add manually" in page.text
    assert 'href="/setup"' in page.text


