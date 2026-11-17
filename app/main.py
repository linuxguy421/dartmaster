from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.brackets.loader import BracketLoadError, available_brackets, load_bracket
from app.brackets.scheduler import SchedulerMode
from app.registration import (
    Gender,
    RegistrationError,
    TournamentRoster,
    create_teams_from_draw,
)
from app.registration.store import RegistrationDraftStore
from app.state import TournamentSession, TournamentStateStore

ROOT = Path(__file__).resolve().parent.parent
BRACKET_DIRECTORY = ROOT / "data"
DEFAULT_DATABASE = ROOT / "data" / "dartmaster.sqlite3"

app = FastAPI(
    title="Dartmaster",
    description="Tournament management for up to four darts boards.",
    version="0.2.0",
)


class PlayerRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    gender: Gender


class DrawRequest(BaseModel):
    mixed_draws: dict[str, int]
    draw_off_draws: dict[str, int] = Field(default_factory=dict)


class SeedRequest(BaseModel):
    bracket_file: str
    assignments: dict[str, str]


class TournamentRequest(BaseModel):
    bracket_file: str
    board_count: int = Field(default=4, ge=1, le=4)
    scheduler_mode: SchedulerMode = SchedulerMode.MANUAL


def database_path() -> str:
    return os.environ.get("DARTMASTER_DB_PATH", str(DEFAULT_DATABASE))


def registration_store() -> RegistrationDraftStore:
    return RegistrationDraftStore(database_path())


def tournament_store() -> TournamentStateStore:
    return TournamentStateStore(database_path())


def bracket_path(filename: str) -> Path:
    if Path(filename).name != filename or not filename.endswith("teamD.json"):
        raise HTTPException(status_code=400, detail="Invalid bracket filename")
    candidate = BRACKET_DIRECTORY / filename
    if candidate not in available_brackets(BRACKET_DIRECTORY):
        raise HTTPException(status_code=404, detail="Bracket not found")
    return candidate


def required_seeds(definition) -> list[str]:
    seeds = {
        reference
        for game in definition.games.values()
        if isinstance(game, dict)
        for reference in game.get("teams", [])
        if isinstance(reference, str) and re.fullmatch(r"T[1-9][0-9]*", reference)
    }
    return sorted(seeds, key=lambda seed: int(seed[1:]))


def registration_payload(roster: TournamentRoster, draw_state=None) -> dict:
    return {
        "players": [
            {
                "player_id": player.player_id,
                "display_name": player.display_name,
                "gender": player.gender.value,
            }
            for player in roster.players.values()
        ],
        "teams": [
            {
                "team_id": team.team_id,
                "name": team.name,
                "player_one": roster.players[team.player_one_id].display_name,
                "player_two": roster.players[team.player_two_id].display_name,
                "player_one_id": team.player_one_id,
                "player_two_id": team.player_two_id,
            }
            for team in roster.teams.values()
        ],
        "seed_assignments": dict(roster.seed_assignments),
        "draw": draw_state,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return (ROOT / "app" / "templates" / "registration.html").read_text(encoding="utf-8")


@app.get("/api/brackets")
def list_brackets() -> list[dict]:
    output = []
    for path in available_brackets(BRACKET_DIRECTORY):
        definition = load_bracket(path)
        output.append(
            {
                "filename": path.name,
                "name": definition.tournament_name,
                "team_count": len(required_seeds(definition)),
                "diagnostics": [item.message for item in definition.diagnostics],
            }
        )
    return output


@app.get("/api/registration")
def get_registration() -> dict:
    try:
        roster, draw_state = registration_store().load()
        return registration_payload(roster, draw_state)
    except RegistrationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/registration/players", status_code=201)
def add_player(request: PlayerRequest) -> dict:
    roster, draw_state = registration_store().load()
    if roster.teams:
        raise HTTPException(
            status_code=409,
            detail="Teams have already been drawn. Reset the draw before changing players.",
        )
    try:
        player = roster.register_player(
            uuid4().hex, request.display_name, request.gender
        )
        registration_store().save(roster, draw_state)
    except RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "player_id": player.player_id,
        "display_name": player.display_name,
        "gender": player.gender.value,
    }


@app.delete("/api/registration/players/{player_id}", status_code=204)
def remove_player(player_id: str) -> None:
    roster, draw_state = registration_store().load()
    if roster.teams:
        raise HTTPException(status_code=409, detail="Reset the draw before removing players")
    if player_id not in roster.players:
        raise HTTPException(status_code=404, detail="Player not found")
    del roster.players[player_id]
    registration_store().save(roster, draw_state)


@app.post("/api/registration/draw")
def draw_teams(request: DrawRequest) -> dict:
    store = registration_store()
    roster, _ = store.load()
    try:
        result = create_teams_from_draw(
            roster,
            request.mixed_draws,
            request.draw_off_draws or None,
        )
        draw_state = {
            "first_gender": result.first_gender.value,
            "draw_order": [gender.value for gender in result.draw_order],
            "mixed_draws": request.mixed_draws,
            "draw_off_draws": request.draw_off_draws,
            "mixed_team_ids": [team.team_id for team in result.mixed_teams],
            "draw_off_team_ids": [team.team_id for team in result.draw_off_teams],
        }
        store.save(roster, draw_state)
    except RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return registration_payload(roster, draw_state)


@app.delete("/api/registration/draw")
def reset_draw() -> dict:
    store = registration_store()
    roster, _ = store.load()
    roster.teams.clear()
    roster.seed_assignments.clear()
    store.save(roster, None)
    return registration_payload(roster)


@app.put("/api/registration/seeds")
def assign_seeds(request: SeedRequest) -> dict:
    store = registration_store()
    roster, draw_state = store.load()
    if not roster.teams:
        raise HTTPException(status_code=409, detail="Draw teams before assigning seeds")
    try:
        definition = load_bracket(bracket_path(request.bracket_file))
        candidate = TournamentRoster.from_dict(roster.to_dict())
        candidate.seed_assignments.clear()
        for seed, team_id in request.assignments.items():
            candidate.assign_seed(seed, team_id)
        candidate.validate_for_bracket(definition)
        store.save(candidate, draw_state)
    except (RegistrationError, BracketLoadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return registration_payload(candidate, draw_state)


@app.post("/api/tournaments", status_code=201)
def create_tournament(request: TournamentRequest) -> dict:
    store = registration_store()
    roster, _ = store.load()
    try:
        definition = load_bracket(bracket_path(request.bracket_file))
        entrants = roster.runtime_entrants(definition)
        tournament_id = uuid4().hex
        session = TournamentSession.create(
            tournament_id,
            request.bracket_file,
            definition,
            entrants,
            tournament_store(),
            board_count=request.board_count,
            mode=request.scheduler_mode,
            roster=roster,
        )
    except (RegistrationError, BracketLoadError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "tournament_id": session.tournament_id,
        "bracket_file": session.bracket_file,
        "team_count": len(entrants),
        "scheduler_mode": session.scheduler.mode.value,
    }
