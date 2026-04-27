from dataclasses import dataclass
from enum import Enum, StrEnum


class Position(Enum):
    GKP = 1
    DEF = 2
    MID = 3
    FWD = 4


class Chip(StrEnum):
    BB = "bboost"
    TC = "3xc"
    FH = "freehit"
    WC = "wildcard"


@dataclass
class Player:
    id: int
    name: str
    position: Position
    history: list[int]


@dataclass
class Pick:
    player_id: int
    multiplier: int


@dataclass
class Gameweek:
    round: int
    active_chip: Chip | None
    points: int
    points_on_bench: int
    picks: list[Pick]
