from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True, slots=True)
class Player:
    player_id: str
    display_name: str
    gender: Gender


@dataclass(frozen=True, slots=True)
class Team:
    team_id: str
    name: str
    male_player_id: str
    female_player_id: str
