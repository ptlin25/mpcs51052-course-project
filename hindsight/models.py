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

    def __hash__(self) -> int:
        return self.id


@dataclass(frozen=True)
class Pick:
    player: Player
    multiplier: int


@dataclass(frozen=True)
class Gameweek:
    round: int
    active_chip: Chip | None
    points: int
    points_on_bench: int
    picks: list[Pick]
