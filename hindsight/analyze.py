from dataclasses import dataclass
from typing import NamedTuple

from .data import FPLData
from .models import Position, Chip, Player, Gameweek


class PlayerPoints(NamedTuple):
    player: Player
    points: int


@dataclass(frozen=True)
class GameweekAnalysis:
    round: int
    active_chip: Chip | None
    raw_points: int  # raw actual starting 11
    captain: PlayerPoints | None
    points_on_bench: int
    optimal_raw_points: int  # raw optimal starting 11
    optimal_captain: PlayerPoints
    should_bench: list[PlayerPoints]
    should_start: list[PlayerPoints]


@dataclass(frozen=True)
class SeasonAnalysis:
    total_points: int
    optimal_points: int
    gameweek_analyses: dict[str, GameweekAnalysis]


class Analyzer:
    def __init__(self, data: FPLData):
        self._players = data.players
        self._gameweeks = data.gameweeks

    def _get_player_gameweek_points(self, player_id: int, round: int) -> int:
        return self._players[player_id].history[round - 1]

    def _get_optimal_starters(self, round: int) -> set[PlayerPoints]:
        gameweek: Gameweek = self._gameweeks[round]

        by_pos: dict[Position, list[PlayerPoints]] = {pos: [] for pos in Position}
        for pick in gameweek.picks:
            player: Player = pick.player
            pos: Position = player.position
            points: int = self._get_player_gameweek_points(player.id, gameweek.round)
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
            by_pos[Position.DEF][3:]
            + by_pos[Position.MID][2:]
            + by_pos[Position.FWD][1:]
        )
        selected += sorted(remaining, key=lambda pp: pp.points, reverse=True)[:4]
        return set(selected)

    def analyze_gameweek(self, round: int) -> GameweekAnalysis:
        gameweek: Gameweek = self._gameweeks[round]
        starters: set[PlayerPoints] = set()
        captain: PlayerPoints | None = None
        for pick in gameweek.picks:
            pp = PlayerPoints(
                player=pick.player,
                points=self._get_player_gameweek_points(pick.player.id, round),
            )
            if pick.multiplier > 0:
                starters.add(pp)
            if pick.multiplier >= 2:
                captain = pp

        optimal_starters: set[PlayerPoints] = self._get_optimal_starters(round)
        # optimal captain is the player that scored the most points
        optimal_captain: PlayerPoints = max(optimal_starters, key=lambda p: p.points)
        # If the actual captain scored the same number of points, keep the actual captain
        if captain and optimal_captain.points == captain.points:
            optimal_captain = captain

        should_bench: list[PlayerPoints] = [p for p in optimal_starters - starters]
        should_start: list[PlayerPoints] = [p for p in starters - optimal_starters]

        raw_points: int = sum(pp.points for pp in starters)
        optimal_raw_points: int = sum(pp.points for pp in optimal_starters)

        return GameweekAnalysis(
            round=round,
            active_chip=gameweek.active_chip,
            raw_points=raw_points,
            captain=captain,
            points_on_bench=gameweek.points_on_bench,
            optimal_raw_points=optimal_raw_points,
            optimal_captain=optimal_captain,
            should_bench=should_bench,
            should_start=should_start,
        )

    def optimal_chip_assignment(self, gameweeks: dict[int, GameweekAnalysis]):
        # Score each GW for TC and BB value
        tc_scores = {
            gw: a.optimal_captain.points
            for gw, a in gameweeks.items()
            if a.active_chip not in (Chip.FH, Chip.WC)
        }
        bb_scores = {
            gw: a.points_on_bench
            for gw, a in gameweeks.items()
            if a.active_chip not in (Chip.FH, Chip.WC)
        }

        best_tc_gw = max(tc_scores, key=lambda k: tc_scores[k])
        best_bb_gw = max(bb_scores, key=lambda k: bb_scores[k])

        if best_tc_gw != best_bb_gw:
            # No conflict
            return best_tc_gw, best_bb_gw

        # Conflict — try all 3 non-conflicting combinations
        conflicting_gw = best_tc_gw
        candidates = [
            # TC on best, BB on second best BB gw
            (
                conflicting_gw,
                max(
                    [gw for gw in bb_scores if gw != conflicting_gw],
                    key=lambda k: bb_scores[k],
                ),
            ),
            # BB on best, TC on second best TC gw
            (
                max(
                    [gw for gw in tc_scores if gw != conflicting_gw],
                    key=lambda k: tc_scores[k],
                ),
                conflicting_gw,
            ),
        ]

        return max(candidates, key=lambda pair: tc_scores[pair[0]] + bb_scores[pair[1]])

    def analyze_season(self):
        gameweek_analyses: list[GameweekAnalysis] = []
