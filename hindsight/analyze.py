import asyncio
from dataclasses import dataclass

from .data import FPLData, fetch_all
from .models import Position, Chip, Player, Pick, Gameweek


@dataclass(frozen=True)
class PlayerPoints:
    player: Player
    points: int


@dataclass(frozen=True)
class GameweekAnalysis:
    round: int
    active_chip: Chip | None
    actual_points: int  # raw actual starting 11
    captain_points: int
    points_on_bench: int
    optimal_points: int  # raw optimal starting 11
    optimal_captain_points: int
    should_bench: list[PlayerPoints]
    should_start: list[PlayerPoints]


def _get_player_gameweek_points(data: FPLData, player_id: int, round: int) -> int:
    return data.players[player_id].history[round - 1]


def _get_optimal_selection(data: FPLData, round: int) -> list[PlayerPoints]:
    gameweek: Gameweek = data.gameweeks[round - 1]
    by_pos: dict[Position, list[PlayerPoints]] = {pos: [] for pos in Position}

    for pick in gameweek.picks:
        player: Player = data.players[pick.player_id]
        pos: Position = player.position
        points: int = _get_player_gameweek_points(data, player.id, gameweek.round)
        by_pos[pos].append(PlayerPoints(player, points))

    for pos in by_pos:
        by_pos[pos].sort(key=lambda pd: -pd.points)

    # fill minimums: 1 GKP, 3 DEF, 2 MID, 1 FWD
    selected: list[PlayerPoints] = (
        by_pos[Position.GKP][:1]
        + by_pos[Position.DEF][:3]
        + by_pos[Position.MID][:2]
        + by_pos[Position.FWD][:1]
    )

    # fill 4 flex spots from remaining outfield players
    remaining: list[PlayerPoints] = (
        by_pos[Position.DEF][3:] + by_pos[Position.MID][2:] + by_pos[Position.FWD][1:]
    )

    selected += sorted(remaining, key=lambda pp: pp.points, reverse=True)[:4]
    return selected


def analyze_gameweek(data: FPLData, round: int):
    gameweek: Gameweek = data.gameweeks[round - 1]
    actual_starters: set[int] = {
        pick.player_id for pick in gameweek.picks if pick.multiplier > 0
    }
    optimal_selection: list[PlayerPoints] = _get_optimal_selection(data, round)
    optimal_ids: set[int] = {pp.player.id for pp in optimal_selection}

    should_bench: list[PlayerPoints] = [
        PlayerPoints(
            player=data.players[pid],
            points=_get_player_gameweek_points(data, pid, round),
        )
        for pid in actual_starters - optimal_ids
    ]
    should_start: list[PlayerPoints] = [
        PlayerPoints(
            player=data.players[pid],
            points=_get_player_gameweek_points(data, pid, round),
        )
        for pid in optimal_ids - actual_starters
    ]

    actual_points: int = sum(
        _get_player_gameweek_points(data, pid, round) for pid in actual_starters
    )
    optimal_points: int = sum(pp.points for pp in optimal_selection)

    captain_pick: Pick = next(pick for pick in gameweek.picks if pick.multiplier >= 2)
    captain_points: int = _get_player_gameweek_points(
        data, captain_pick.player_id, round
    )
    optimal_captain_points: int = max(pp.points for pp in optimal_selection)

    return GameweekAnalysis(
        round=round,
        active_chip=gameweek.active_chip,
        actual_points=actual_points,
        captain_points=captain_points,
        points_on_bench=gameweek.points_on_bench,
        optimal_points=optimal_points,
        optimal_captain_points=optimal_captain_points,
        should_bench=should_bench,
        should_start=should_start,
    )
