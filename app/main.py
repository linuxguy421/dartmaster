from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.brackets.loader import BracketLoadError, available_brackets, load_bracket
from app.brackets.scheduler import BoardSchedulerError
from app.registration import (
    Gender,
    RegistrationError,
    TournamentRoster,
    create_teams_from_draw,
)
from app.registration.store import RegistrationDraftStore
from app.state import TournamentSession, TournamentStateStore, TournamentStoreError

ROOT = Path(__file__).resolve().parent.parent
BRACKET_DIRECTORY = ROOT / "data"
DEFAULT_DATABASE = ROOT / "data" / "dartmaster.sqlite3"

app = FastAPI(
    title="Dartmaster",
    description="Tournament management for up to four darts boards.",
    version="0.2.0",
)

app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


class PlayerRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    gender: Gender


class DrawRequest(BaseModel):
    mixed_draws: dict[str, int]
    draw_off_draws: dict[str, int] = Field(default_factory=dict)


class TournamentRequest(BaseModel):
    bracket_file: str


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
                "playing_role": (
                    "female"
                    if draw_state and player.player_id in draw_state.get("female_role_ids", [])
                    else player.gender.value
                ),
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    # A visit to the registration page always begins a fresh registration.
    # Tournament snapshots are stored separately and remain available to resume.
    registration_store().clear()
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
    if len(roster.players) % 2:
        raise HTTPException(
            status_code=400,
            detail="An even number of players is required to form two-player teams.",
        )
    if len(roster.players) < 6:
        raise HTTPException(
            status_code=400,
            detail="At least 6 players are required (3 teams minimum).",
        )
    try:
        result = create_teams_from_draw(
            roster,
            request.mixed_draws,
            request.draw_off_draws or None,
        )
        ordered_teams = sorted(
            roster.teams.values(),
            key=lambda team: min(
                request.mixed_draws[team.player_one_id],
                request.mixed_draws[team.player_two_id],
            ),
        )
        for index, team in enumerate(ordered_teams, start=1):
            roster.assign_seed(f"T{index}", team.team_id)

        draw_state = {
            "first_gender": result.first_gender.value,
            "draw_order": [gender.value for gender in result.draw_order],
            "mixed_draws": request.mixed_draws,
            "draw_off_draws": request.draw_off_draws,
            "mixed_team_ids": [team.team_id for team in result.mixed_teams],
            "draw_off_team_ids": [team.team_id for team in result.draw_off_teams],
            "female_role_ids": list(result.female_role_ids),
            "team_draw_order": [team.team_id for team in ordered_teams],
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


@app.post("/api/tournaments", status_code=201)
def create_tournament(request: TournamentRequest) -> dict:
    store = registration_store()
    roster, _ = store.load()
    if len(roster.players) < 6 or len(roster.teams) < 3:
        raise HTTPException(
            status_code=400,
            detail="At least 6 players (3 teams) are required to start a tournament.",
        )
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
            board_count=4,
            roster=roster,
        )
    except (RegistrationError, BracketLoadError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.clear()
    return {
        "tournament_id": session.tournament_id,
        "bracket_file": session.bracket_file,
        "team_count": len(entrants),
        "board_count": 4,
        "dashboard_url": f"/tournaments/{session.tournament_id}",
    }


@app.get("/api/tournaments")
def list_unfinished_tournaments() -> list[dict]:
    try:
        return tournament_store().unfinished()
    except TournamentStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

def tournament_session(tournament_id: str) -> TournamentSession:
    store = tournament_store()
    try:
        snapshot = store.load(tournament_id)
        bracket_file = snapshot.get("bracket_file")
        definition = load_bracket(bracket_path(bracket_file))
        return TournamentSession.restore(tournament_id, definition, store)
    except HTTPException:
        raise
    except (TournamentStoreError, BracketLoadError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def bracket_payload(session: TournamentSession) -> list[dict]:
    """Return one ordered operator-facing entry per logical bracket match."""
    runtime = session.runtime
    ready_by_game = {
        match.source_game_id: match for match in runtime.ready_matches()
    }
    assignments = {
        assignment.match.match_id: assignment
        for assignment in session.scheduler.assignments
    }
    entries = []
    game_rounds = {}

    for game_id in runtime.definition.game_order:
        if game_id == "GGF":
            continue

        is_championship = game_id == "GF"
        match_id = "CHAMPIONSHIP" if is_championship else game_id
        source_game_id = (
            "GGF"
            if is_championship
            and runtime.championship_phase.value == "reset"
            else game_id
        )
        result = runtime.results.get(source_game_id)
        ready = ready_by_game.get(source_game_id)
        assignment = assignments.get(match_id)

        if result is not None and is_championship:
            # A completed GF may still be followed by its conditional reset.
            status = "reset_pending"
            participants = [result.winner, result.loser]
            winner = result.winner
            loser = result.loser
        elif result is not None:
            status = "completed"
            participants = [result.winner, result.loser]
            winner = result.winner
            loser = result.loser
        elif ready is not None:
            participants = list(ready.participants)
            status = "in_progress" if assignment else "ready"
            winner = loser = None
        else:
            game = runtime.definition.games.get(game_id, {})
            references = (
                list(game.get("teams", [])) if isinstance(game, dict) else []
            )
            participants = []
            for reference in references:
                if not isinstance(reference, str):
                    participants.append("TBD")
                    continue
                if reference in runtime.entrants:
                    participants.append(runtime.entrants[reference])
                    continue
                route_match = re.fullmatch(r"([WL])-(.+)", reference)
                if route_match:
                    prior_result = runtime.results.get(route_match.group(2))
                    if prior_result is not None:
                        participants.append(
                            prior_result.winner
                            if route_match.group(1) == "W"
                            else prior_result.loser
                        )
                    else:
                        outcome = "Winner" if route_match.group(1) == "W" else "Loser"
                        participants.append(f"{outcome} of {route_match.group(2)}")
                else:
                    participants.append(reference)
            status = "waiting"
            winner = loser = None

        if is_championship and runtime.championship_phase.value == "complete":
            final_result = runtime.results.get("GGF") or runtime.results.get("GF")
            if final_result is not None:
                status = "completed"
                participants = [final_result.winner, final_result.loser]
                winner, loser = final_result.winner, final_result.loser

        game_definition = runtime.definition.games.get(game_id, {})
        placement = game_definition.get("placement_match", {})
        placement_label = (
            f"{placement['winner']} Place"
            if isinstance(placement, dict)
            and placement.get("winner")
            and placement.get("loser") == "4th"
            else (
                f"{placement['winner']} / {placement['loser']} Place"
                if isinstance(placement, dict)
                and placement.get("winner")
                and placement.get("loser")
                else None
            )
        )
        bracket_type = (
            "championship"
            if is_championship
            else "winners"
            if str(game_definition.get("is_winnerbracket", "")).lower() == "true"
            else "losers"
        )
        dependencies = [
            reference[2:]
            for reference in game_definition.get("teams", [])
            if isinstance(reference, str)
            and re.fullmatch(r"[WL]-.+", reference)
        ]
        round_number = (
            max((game_rounds.get(dependency, 0) for dependency in dependencies), default=-1) + 1
        )
        game_rounds[game_id] = round_number

        placement_payouts = None
        placement_players = None
        if isinstance(placement, dict) and placement.get("winner") and placement.get("loser"):
            placement_payouts = {
                "winner_place": str(placement["winner"]),
                "loser_place": str(placement["loser"]),
            }
            if result is not None and session.roster is not None:
                entrant_players = {}
                for seed, team_id in session.roster.seed_assignments.items():
                    team = session.roster.teams[team_id]
                    entrant = runtime.entrants[seed]
                    entrant_players[entrant] = (
                        f"{session.roster.players[team.player_one_id].display_name} / "
                        f"{session.roster.players[team.player_two_id].display_name}"
                    )
                placement_players = {
                    placement_payouts["winner_place"]: entrant_players.get(result.winner, result.winner),
                    placement_payouts["loser_place"]: entrant_players.get(result.loser, result.loser),
                }

        entries.append({
            "match_id": match_id,
            "source_game_id": source_game_id,
            "label": "Championship Match" if is_championship else f"Match {game_id}",
            "placement_label": placement_label,
            "placement_payouts": placement_payouts,
            "placement_players": placement_players,
            "status": status,
            "participants": participants,
            "winner": winner,
            "loser": loser,
            "board_id": assignment.board_id if assignment else None,
            "phase": assignment.match.phase.value if assignment and assignment.match.phase else None,
            "bracket_type": bracket_type,
            "round": round_number,
            "winner_advances_to": dict(game_definition.get("winner_advances_to", {})),
            "loser_drops_to": dict(game_definition.get("loser_drops_to", {})),
        })

    return entries


def tournament_payload(session: TournamentSession) -> dict:
    assignments = {item.board_id: item for item in session.scheduler.assignments}
    boards = []
    for board_id in range(1, 5):
        assignment = assignments.get(board_id)
        match = assignment.match if assignment else None
        boards.append({
            "board_id": board_id,
            "configured": True,
            "enabled": True,
            "status": (
                "blocked" if assignment and assignment.blocked_reason
                else "in_progress" if assignment
                else "available"
            ),
            "match": ({
                "match_id": match.match_id,
                "source_game_id": match.source_game_id,
                "participants": list(match.participants),
                "phase": match.phase.value if match.phase else None,
                "placement_label": next((entry["placement_label"] for entry in bracket_payload(session) if entry["match_id"] == match.match_id), None),
                "blocked_reason": assignment.blocked_reason,
            } if match else None),
        })
    display_results = [
        {"game_id": result.game_id, "winner": result.winner, "loser": result.loser}
        for result in session.runtime.results.values()
        if result.game_id not in {"GF", "GGF"}
    ]
    if session.runtime.champion is not None:
        final_result = (
            session.runtime.results.get("GGF")
            or session.runtime.results.get("GF")
        )
        if final_result is not None:
            display_results.append({
                "game_id": "CHAMPIONSHIP",
                "winner": final_result.winner,
                "loser": final_result.loser,
            })

    return {
        "tournament_id": session.tournament_id,
        "bracket_file": session.bracket_file,
        "payouts": {
            "currency": session.runtime.definition.currency,
            "prizes": dict(session.runtime.definition.prizes),
            "prizes_with_side_pot": dict(session.runtime.definition.prizes_with_side_pot),
            "side_pot_amount": session.runtime.definition.side_pot_amount,
            "side_pot_contribution_per_player": session.runtime.definition.side_pot_contribution_per_player,
            "side_pot_contribution_per_team": session.runtime.definition.side_pot_contribution_per_player * 2,
        },
        "scheduler": {
            "board_count": 4,
            "free_boards": list(session.scheduler.free_boards),
        },
        "ready_matches": [
            {
                "match_id": match.match_id,
                "source_game_id": match.source_game_id,
                "participants": list(match.participants),
                "phase": match.phase.value if match.phase else None,
                "placement_label": next((entry["placement_label"] for entry in bracket_payload(session) if entry["match_id"] == match.match_id), None),
            }
            for match in session.scheduler.ready_matches(session.runtime)
        ],
        "boards": boards,
        "bracket": bracket_payload(session),
        "results": display_results,
        "championship": {
            "phase": session.runtime.championship_phase.value,
            "champion": session.runtime.champion,
        },
        "complete": session.runtime.champion is not None,
    }


@app.get("/tournaments/{tournament_id}", response_class=HTMLResponse)
def tournament_dashboard(tournament_id: str) -> str:
    tournament_session(tournament_id)
    return (ROOT / "app" / "templates" / "tournament.html").read_text(encoding="utf-8")

@app.get("/tournaments/{tournament_id}/bracket", response_class=HTMLResponse)
def tournament_bracket_view(tournament_id: str) -> str:
    tournament_session(tournament_id)
    return (ROOT / "app" / "templates" / "bracket.html").read_text(encoding="utf-8")


@app.delete("/api/tournaments/{tournament_id}", status_code=204)
def delete_tournament(tournament_id: str) -> None:
    try:
        tournament_store().delete(tournament_id)
    except TournamentStoreError as exc:
        if str(exc).startswith("Unknown tournament:"):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/tournaments/{tournament_id}")
def get_tournament(tournament_id: str) -> dict:
    return tournament_payload(tournament_session(tournament_id))


class AssignMatchRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=80)


@app.post("/api/tournaments/{tournament_id}/boards/{board_id}/assign")
def assign_match_to_board(
    tournament_id: str, board_id: int, request: AssignMatchRequest
) -> dict:
    session = tournament_session(tournament_id)
    try:
        session.assign_match(board_id, request.match_id)
    except (BoardSchedulerError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return tournament_payload(session)


class WinnerRequest(BaseModel):
    winner: str = Field(min_length=1, max_length=160)


@app.post("/api/tournaments/{tournament_id}/boards/{board_id}/winner")
def complete_board_match(tournament_id: str, board_id: int, request: WinnerRequest) -> dict:
    session = tournament_session(tournament_id)
    try:
        session.complete_match(board_id, request.winner)
    except (BoardSchedulerError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return tournament_payload(session)
