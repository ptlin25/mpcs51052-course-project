import asyncio
from dataclasses import dataclass
from typing import NamedTuple

from hindsight.data import fetch
from hindsight.models import Position, Chip, Player, Gameweek


class PlayerPoints(NamedTuple):
    player: Player
    points: int


@dataclass(frozen=True)
class GameweekAnalysis:
    round: int
    active_chip: Chip | None  # chip played this gameweek
    transfers_cost: int
    total_squad_points: int
    captain: PlayerPoints | None
    starters: frozenset[PlayerPoints]
    optimal_starters: frozenset[PlayerPoints]

    @property
    def captain_points(self) -> int:
        return self.captain.points if self.captain else 0

    @property
    def raw_points(self) -> int:
        return sum(p.points for p in self.starters)

    @property
    def optimal_raw_points(self) -> int:
        return sum(p.points for p in self.optimal_starters)

    @property
    def should_bench(self) -> list[PlayerPoints]:
        return sorted(
            [p for p in self.starters - self.optimal_starters],
            key=lambda p: p.player.position.value,
        )

    @property
    def should_start(self) -> list[PlayerPoints]:
        return sorted(
            [p for p in self.optimal_starters - self.starters],
            key=lambda p: p.player.position.value,
        )

    @property
    def optimal_captain(self) -> PlayerPoints:
        best = max(self.optimal_starters, key=lambda p: p.points)
        if self.captain and best.points == self.captain.points:
            return self.captain
        return best

    @property
    def actual_points_no_chips(self) -> int:
        return self.raw_points + self.captain_points

    @property
    def optimal_points_no_chips(self) -> int:
        return self.optimal_raw_points + self.optimal_captain.points

    @property
    def points_on_actual_bench(self) -> int:
        return self.total_squad_points - self.raw_points

    @property
    def points_on_optimal_bench(self) -> int:
        return self.total_squad_points - self.optimal_raw_points


@dataclass(frozen=True)
class ChipUsage:
    chip: Chip
    chip_bonus: int


@dataclass(frozen=True)
class SeasonAnalysis:
    total_transfers_cost: int
    actual_points_no_chips: int
    optimal_points_no_chips: int
    actual_chip_usage: dict[int, ChipUsage]
    optimal_selection_chip_usage: dict[int, ChipUsage]
    optimal_chip_usage: dict[int, ChipUsage]
    gameweek_analyses: dict[int, GameweekAnalysis]

    @property
    def actual_chip_bonus(self) -> int:
        return sum(u.chip_bonus for u in self.actual_chip_usage.values())

    @property
    def optimal_selection_chip_bonus(self) -> int:
        return sum(u.chip_bonus for u in self.optimal_selection_chip_usage.values())

    @property
    def optimal_chip_bonus(self) -> int:
        return sum(u.chip_bonus for u in self.optimal_chip_usage.values())

    @property
    def actual_total_points(self) -> int:
        return (
            self.actual_points_no_chips
            + self.actual_chip_bonus
            - self.total_transfers_cost
        )

    @property
    def optimal_selection_total_points(self) -> int:
        return self.optimal_points_no_chips + self.optimal_selection_chip_bonus

    @property
    def optimal_total_points(self) -> int:
        return self.optimal_points_no_chips + self.optimal_chip_bonus

    def actual_chip_bonus_for(self, round: int) -> int:
        usage: ChipUsage | None = self.actual_chip_usage.get(round)
        return usage.chip_bonus if usage else 0

    def optimal_selection_chip_bonus_for(self, round: int) -> int:
        usage: ChipUsage | None = self.optimal_selection_chip_usage.get(round)
        return usage.chip_bonus if usage else 0

    def optimal_chip_bonus_for(self, round: int) -> int:
        usage: ChipUsage | None = self.optimal_chip_usage.get(round)
        return usage.chip_bonus if usage else 0


class Analyzer:
    def __init__(self, team_id: int):
        self._gameweeks: dict[int, Gameweek] = asyncio.run(fetch(team_id))

    def _get_optimal_starters(self, round: int) -> set[PlayerPoints]:
        gameweek: Gameweek = self._gameweeks[round]

        by_pos: dict[Position, list[PlayerPoints]] = {pos: [] for pos in Position}
        for pick in gameweek.picks:
            player: Player = pick.player
            pos: Position = player.position
            points: int = player.get_gameweek_points(round)
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
                points=pick.player.get_gameweek_points(round),
            )
            total_squad_points += pp.points
            if pick.position <= 11:
                starters.add(pp)
            if pick.multiplier >= 2:
                captain = pp

        optimal_starters: set[PlayerPoints] = self._get_optimal_starters(round)

        return GameweekAnalysis(
            round=round,
            active_chip=gameweek.active_chip,
            transfers_cost=gameweek.transfers_cost,
            total_squad_points=total_squad_points,
            captain=captain,
            starters=frozenset(starters),
            optimal_starters=frozenset(optimal_starters),
        )

    def _get_actual_chip_timing(self) -> dict[int, Chip]:
        chip_timing: dict[int, Chip] = {}
        for round, gameweek in self._gameweeks.items():
            if (chip := gameweek.active_chip) is not None:
                chip_timing[round] = chip
        return chip_timing

    def _get_optimal_assignment(
        self, tc_scores: dict[int, int], bb_scores: dict[int, int]
    ) -> tuple[int, int]:
        best_tc_gw: int = max(tc_scores, key=lambda gw: tc_scores[gw])
        best_bb_gw: int = max(bb_scores, key=lambda gw: bb_scores[gw])

        if best_tc_gw != best_bb_gw:
            # No conflict
            return best_tc_gw, best_bb_gw

        # Conflict — try both non-conflicting combinations
        conflicting_gw: int = best_tc_gw
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

    def _get_optimal_chip_timing(
        self, gw_analyses: dict[int, GameweekAnalysis]
    ) -> dict[int, Chip]:
        actual_chip_timing = self._get_actual_chip_timing()
        optimal_chip_timing: dict[int, Chip] = {
            gw: chip
            for gw, chip in actual_chip_timing.items()
            if chip in {Chip.FH, Chip.WC}
        }

        def _get_optimal_chip_timing_half(
            half_analyses: dict[int, GameweekAnalysis],
        ) -> None:
            # Score each GW for TC and BB value
            tc_scores: dict[int, int] = {
                gw: a.optimal_captain.points
                for gw, a in half_analyses.items()
                if a.active_chip not in {Chip.FH, Chip.WC}
            }
            bb_scores: dict[int, int] = {
                gw: a.points_on_optimal_bench
                for gw, a in half_analyses.items()
                if a.active_chip not in {Chip.FH, Chip.WC}
            }

            best_tc_gw, best_bb_gw = self._get_optimal_assignment(tc_scores, bb_scores)
            optimal_chip_timing[best_tc_gw] = Chip.TC
            optimal_chip_timing[best_bb_gw] = Chip.BB

        first_half: dict[int, GameweekAnalysis] = {
            gw: a for gw, a in gw_analyses.items() if gw <= 19
        }
        second_half: dict[int, GameweekAnalysis] = {
            gw: a for gw, a in gw_analyses.items() if gw > 19
        }
        _get_optimal_chip_timing_half(first_half)
        _get_optimal_chip_timing_half(second_half)

        return optimal_chip_timing

    def analyze_season(self) -> SeasonAnalysis:
        gw_analyses: dict[int, GameweekAnalysis] = {
            round: self.analyze_gameweek(round) for round in self._gameweeks
        }

        actual_chip_timing: dict[int, Chip] = self._get_actual_chip_timing()
        optimal_chip_timing: dict[int, Chip] = self._get_optimal_chip_timing(gw_analyses)

        actual_chip_usage: dict[int, ChipUsage] = {}
        optimal_selection_chip_usage: dict[int, ChipUsage] = {}
        optimal_chip_usage: dict[int, ChipUsage] = {}

        total_transfers_cost: int = 0
        actual_points_no_chips: int = 0
        optimal_points_no_chips: int = 0

        for gw, analysis in gw_analyses.items():
            total_transfers_cost += analysis.transfers_cost
            actual_captain_points: int = (
                c.points if (c := analysis.captain) is not None else 0
            )
            gw_actual: int = analysis.raw_points + actual_captain_points
            actual_points_no_chips += gw_actual

            optimal_captain_points: int = analysis.optimal_captain.points
            gw_optimal: int = analysis.optimal_raw_points + optimal_captain_points
            optimal_points_no_chips += gw_optimal

            if gw in actual_chip_timing:
                match chip := actual_chip_timing[gw]:
                    case Chip.TC:
                        actual_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=actual_captain_points
                        )
                        optimal_selection_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=optimal_captain_points
                        )
                    case Chip.BB:
                        actual_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=analysis.points_on_actual_bench
                        )
                        optimal_selection_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=analysis.points_on_optimal_bench
                        )
                    case Chip.FH | Chip.WC:
                        actual_chip_usage[gw] = ChipUsage(chip=chip, chip_bonus=0)
                        optimal_selection_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=0
                        )

            if gw in optimal_chip_timing:
                match chip := optimal_chip_timing[gw]:
                    case Chip.TC:
                        optimal_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=optimal_captain_points
                        )
                    case Chip.BB:
                        optimal_chip_usage[gw] = ChipUsage(
                            chip=chip, chip_bonus=analysis.points_on_optimal_bench
                        )
                    case Chip.FH | Chip.WC:
                        optimal_chip_usage[gw] = ChipUsage(chip=chip, chip_bonus=0)

        return SeasonAnalysis(
            total_transfers_cost=total_transfers_cost,
            actual_points_no_chips=actual_points_no_chips,
            optimal_points_no_chips=optimal_points_no_chips,
            actual_chip_usage=actual_chip_usage,
            optimal_selection_chip_usage=optimal_selection_chip_usage,
            optimal_chip_usage=optimal_chip_usage,
            gameweek_analyses=gw_analyses,
        )
