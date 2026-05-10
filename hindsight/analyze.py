import asyncio
from dataclasses import dataclass
from typing import NamedTuple

from hindsight.data import FPLData, fetch_all
from hindsight.models import Position, Chip, Player, Gameweek


class PlayerPoints(NamedTuple):
    player: Player
    points: int


@dataclass(frozen=True)
class GameweekAnalysis:
    round: int
    active_chip: Chip | None            # chip played this gameweek
    transfers_cost: int
    total_squad_points: int
    raw_points: int                     # raw actual starting 11
    captain: PlayerPoints | None        # captain after automatic substitutions
    optimal_raw_points: int             # raw optimal starting 11
    optimal_captain: PlayerPoints       # optimal captain (player who scored the most points)
    should_bench: list[PlayerPoints]    
    should_start: list[PlayerPoints]


@dataclass(frozen=True)
class SeasonAnalysis:
    total_points: int
    optimal_points: int
    total_transfers_cost: int
    gameweek_analyses: dict[int, GameweekAnalysis]


class Analyzer:
    def __init__(self, team_id: int):
        data: FPLData = asyncio.run(fetch_all(team_id))
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
        total_squad_points: int = 0
        for pick in gameweek.picks:
            pp = PlayerPoints(
                player=pick.player,
                points=self._get_player_gameweek_points(pick.player.id, round),
            )
            total_squad_points += pp.points
            if pick.position <= 11:
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
            transfers_cost=gameweek.transfers_cost,
            total_squad_points=total_squad_points,
            raw_points=raw_points,
            captain=captain,
            optimal_raw_points=optimal_raw_points,
            optimal_captain=optimal_captain,
            should_bench=should_bench,
            should_start=should_start,
        )

    def optimal_chip_assignment(self, gw_analyses: dict[int, GameweekAnalysis]):
        # Score each GW for TC and BB value
        tc_scores = {
            gw: analysis.optimal_captain.points
            for gw, analysis in gw_analyses.items()
            if analysis.active_chip not in (Chip.FH, Chip.WC)
        }
        bb_scores = {
            gw: analysis.total_squad_points - analysis.optimal_raw_points
            for gw, analysis in gw_analyses.items()
            if analysis.active_chip not in (Chip.FH, Chip.WC)
        }

        best_tc_gw = max(tc_scores, key=lambda gw: tc_scores[gw])
        best_bb_gw = max(bb_scores, key=lambda gw: bb_scores[gw])

        if best_tc_gw != best_bb_gw:
            # No conflict
            return best_tc_gw, best_bb_gw

        # Conflict — try both non-conflicting combinations
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

    def analyze_season(self) -> SeasonAnalysis:
        first_half: dict[int, GameweekAnalysis] = {gw: self.analyze_gameweek(gw) for gw in self._gameweeks if gw <= 19}
        second_half: dict[int, GameweekAnalysis] = {gw: self.analyze_gameweek(gw) for gw in self._gameweeks if gw > 19}

        first_tc_gw, first_bb_gw = self.optimal_chip_assignment(first_half)
        second_tc_gw, second_bb_gw = self.optimal_chip_assignment(second_half)

        total_points: int = 0
        optimal_points: int = 0
        total_transfers_cost: int = 0

        gameweek_analyses: dict[int, GameweekAnalysis] = first_half | second_half
        for gw, analysis in gameweek_analyses.items():
            gw_actual: int = analysis.raw_points + c.points if (c := analysis.captain) is not None else analysis.raw_points
            gw_optimal: int = analysis.optimal_raw_points + analysis.optimal_captain.points

            if analysis.active_chip == Chip.TC:
                gw_actual += c.points if (c := analysis.captain) is not None else 0
            if analysis.active_chip == Chip.BB:
                gw_actual: int = analysis.total_squad_points + c.points if (c := analysis.captain) is not None else analysis.total_squad_points

            if gw == first_tc_gw or gw == second_tc_gw:
                gw_optimal += analysis.optimal_captain.points
            elif gw == first_bb_gw or gw == second_bb_gw:
                gw_optimal: int = analysis.total_squad_points + analysis.optimal_captain.points
            
            total_points += gw_actual
            optimal_points += gw_optimal
            total_transfers_cost += analysis.transfers_cost
            

        return SeasonAnalysis(
            total_points=total_points,
            optimal_points=optimal_points,
            total_transfers_cost=total_transfers_cost,
            gameweek_analyses=gameweek_analyses,
        )
