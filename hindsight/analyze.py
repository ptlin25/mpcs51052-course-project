from dataclasses import dataclass
from typing import NamedTuple

from hindsight.models import Position, Chip, Player, Gameweek


class PlayerPoints(NamedTuple):
    """NamedTuple that contains a Player and the points he scored"""

    player: Player
    points: int


@dataclass(frozen=True)
class GameweekAnalysis:
    """Frozen dataclass that contains the analysis of a gameweek"""

    round: int  # gameweek number
    active_chip: Chip | None  # chip played this gameweek
    transfers_cost: int  # cost of transfers made this gw
    total_squad_points: int  # total points scored by the 15-man team
    captain: PlayerPoints | None  # gw captain (after auto-subs)
    starters: frozenset[PlayerPoints]  # actual starting 11
    optimal_starters: frozenset[PlayerPoints]  # optimal starting 11

    @property
    def captain_points(self) -> int:
        """Points scored by the captain"""
        return self.captain.points if self.captain else 0

    @property
    def raw_points(self) -> int:
        """Points scored by the actual starters without bonuses"""
        return sum(p.points for p in self.starters)

    @property
    def optimal_raw_points(self) -> int:
        """Points scored by the optimal starters without bonuses"""
        return sum(p.points for p in self.optimal_starters)

    @property
    def should_bench(self) -> list[PlayerPoints]:
        """Starters that should have been benched"""
        return sorted(
            [p for p in self.starters - self.optimal_starters],
            key=lambda p: p.player.position.value,
        )

    @property
    def should_start(self) -> list[PlayerPoints]:
        """Substitutes that should have started"""
        return sorted(
            [p for p in self.optimal_starters - self.starters],
            key=lambda p: p.player.position.value,
        )

    @property
    def optimal_captain(self) -> PlayerPoints:
        """Highest scoring player in the squad"""
        best = max(self.optimal_starters, key=lambda p: p.points)
        # keep actual captain if the actual captain is a highest scoring player
        if self.captain and best.points == self.captain.points:
            return self.captain
        return best

    @property
    def actual_points_no_chips(self) -> int:
        """Actual points scored without chip bonuses"""
        return self.raw_points + self.captain_points

    @property
    def optimal_points_no_chips(self) -> int:
        """Optimal points scored without chip bonuses"""
        return self.optimal_raw_points + self.optimal_captain.points

    @property
    def points_on_actual_bench(self) -> int:
        """Points left on the actual bench"""
        return self.total_squad_points - self.raw_points

    @property
    def points_on_optimal_bench(self) -> int:
        """Points left on the optimal bench"""
        return self.total_squad_points - self.optimal_raw_points


@dataclass(frozen=True)
class ChipUsage:
    """Frozen dataclass to store the chip used and the chip bonus points"""

    chip: Chip
    chip_bonus: int


@dataclass(frozen=True)
class SeasonAnalysis:
    """Frozen dataclass to store the analysis of the season"""

    total_transfers_cost: int
    actual_points_no_chips: int
    optimal_points_no_chips: int
    actual_chip_usage: dict[int, ChipUsage]
    optimal_selection_chip_usage: dict[int, ChipUsage]
    optimal_chip_usage: dict[int, ChipUsage]
    gameweek_analyses: dict[int, GameweekAnalysis]

    @property
    def actual_chip_bonus(self) -> int:
        """
        Total chip bonus points from the actual squad selection and
        actual chip timing
        """
        return sum(u.chip_bonus for u in self.actual_chip_usage.values())

    @property
    def optimal_selection_chip_bonus(self) -> int:
        """
        Total chip bonus points with the optimal squad selection and
        actual chip timing
        """
        return sum(u.chip_bonus for u in self.optimal_selection_chip_usage.values())

    @property
    def optimal_chip_bonus(self) -> int:
        """
        Total chip bonus points with the optimal squad selection and
        optimal chip timing
        """
        return sum(u.chip_bonus for u in self.optimal_chip_usage.values())

    @property
    def actual_total_points(self) -> int:
        """Total points"""
        return (
            self.actual_points_no_chips
            + self.actual_chip_bonus
            - self.total_transfers_cost
        )

    @property
    def optimal_selection_total_points(self) -> int:
        """Total points after selection optimizations"""
        return (
            self.optimal_points_no_chips
            + self.optimal_selection_chip_bonus
            - self.total_transfers_cost
        )

    @property
    def optimal_total_points(self) -> int:
        """Total points after selection and chip optimizations"""
        return (
            self.optimal_points_no_chips
            + self.optimal_chip_bonus
            - self.total_transfers_cost
        )

    def actual_chip_bonus_for(self, round: int) -> int:
        """Actual chip bonus for the gameweek"""
        usage: ChipUsage | None = self.actual_chip_usage.get(round)
        return usage.chip_bonus if usage else 0

    def optimal_selection_chip_bonus_for(self, round: int) -> int:
        """Chip bonus for the gameweek with optimal selection"""
        usage: ChipUsage | None = self.optimal_selection_chip_usage.get(round)
        return usage.chip_bonus if usage else 0

    def optimal_chip_bonus_for(self, round: int) -> int:
        """Chip bonus for the gameweek with optimal selection and chip timing"""
        usage: ChipUsage | None = self.optimal_chip_usage.get(round)
        return usage.chip_bonus if usage else 0


class Analyzer:
    """Class that takes in raw data and analyzes it"""

    def __init__(self, gameweeks: dict[int, Gameweek]):
        self._gameweeks = gameweeks

    def _get_optimal_starters(
        self, round: int, actual_starters: set[PlayerPoints]
    ) -> set[PlayerPoints]:
        """
        Returns the optimal starting 11

        This function aggregates the players by position and sorts by
        the number of points scored. A valid starting 11 needs exactly
        one goalkeeper, at least 3 defenders, at least 2 midfielders,
        and at least 1 forward. The minimum requirements are filled
        and then the remaining 4 players are chosen from the highest-
        scoring, remaining outfielders (defenders, midfielders, or
        forwards).

        Among all optimal selections with the same total points, the
        one with the fewest changes from actual_starters is preferred.
        """
        gameweek: Gameweek = self._gameweeks[round]

        # get the players by position
        by_pos: dict[Position, list[PlayerPoints]] = {pos: [] for pos in Position}
        for pick in gameweek.picks:
            player: Player = pick.player
            pos: Position = player.position
            points: int = player.get_gameweek_points(round)
            by_pos[pos].append(PlayerPoints(player, points))

        # sort by points descending; break ties by preferring actual starters
        def sort_key(pp: PlayerPoints) -> tuple[int, int]:
            return (-pp.points, 0 if pp in actual_starters else 1)

        for pos in by_pos:
            by_pos[pos].sort(key=sort_key)

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
        selected += sorted(remaining, key=sort_key)[:4]
        return set(selected)

    def analyze_gameweek(self, round: int) -> GameweekAnalysis:
        """Returns a GameweekAnalysis object for the given gameweek"""
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

        optimal_starters: set[PlayerPoints] = self._get_optimal_starters(
            round, starters
        )

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
        """
        Returns the actual chip timing.

        Returns a dict mapping gameweek to the chip played if
        a chip was actually played that gameweek.
        """
        chip_timing: dict[int, Chip] = {}
        for round, gameweek in self._gameweeks.items():
            if (chip := gameweek.active_chip) is not None:
                chip_timing[round] = chip
        return chip_timing

    def _get_optimal_assignment(
        self, tc_scores: dict[int, int], bb_scores: dict[int, int]
    ) -> tuple[int | None, int | None]:
        """
        Returns the optimal Triple Captain and Bench Boost chip timing.

        Given the Triple Captain scores (dict mapping gameweek to
        chip bonus points if the Triple Captain chip was played that
        gameweek) and the Bench Boost scores (dict mapping gameweek
        to chip bonus points if the Bench Boost chip was played that
        gameweek), returns optimal assignment of chips to maximize
        the bonus points as a tuple (best Triple Captain gw, best
        Bench Boost gw).

        Returns None for a chip if no valid gameweek exists for it.
        Note: only one chip can be played in a gameweek.
        """
        if not tc_scores or not bb_scores:
            return None, None

        best_tc_gw: int = max(tc_scores, key=lambda gw: tc_scores[gw])
        best_bb_gw: int = max(bb_scores, key=lambda gw: bb_scores[gw])

        if best_tc_gw != best_bb_gw:
            # No conflict
            return best_tc_gw, best_bb_gw

        # Conflict — try both non-conflicting combinations
        conflicting_gw: int = best_tc_gw
        remaining_tc = [gw for gw in tc_scores if gw != conflicting_gw]
        remaining_bb = [gw for gw in bb_scores if gw != conflicting_gw]

        if not remaining_tc or not remaining_bb:
            # Only one gameweek available: assign to whichever chip benefits more
            if tc_scores[conflicting_gw] >= bb_scores[conflicting_gw]:
                return conflicting_gw, None
            return None, conflicting_gw

        candidates = [
            # TC on best, BB on second best BB gw
            (conflicting_gw, max(remaining_bb, key=lambda k: bb_scores[k])),
            # BB on best, TC on second best TC gw
            (max(remaining_tc, key=lambda k: tc_scores[k]), conflicting_gw),
        ]

        # return the best assignment
        return max(candidates, key=lambda pair: tc_scores[pair[0]] + bb_scores[pair[1]])

    def _get_optimal_chip_timing(
        self, gw_analyses: dict[int, GameweekAnalysis]
    ) -> dict[int, Chip]:
        """
        Returns the optimal chip timing.

        Returns a dict mapping gameweek number to the chip used that
        gameweek in the optimal chip timing. This program does not
        optimize Free Hit or Wildcard, so the optimal timing for
        those chips will be the same as the actual timing. Each chip
        can be played once in gameweeks 1-19 and once in gameweeks
        20-38. Only one chip can be used during a given gameweek.
        """
        actual_chip_timing = self._get_actual_chip_timing()
        optimal_chip_timing: dict[int, Chip] = {
            gw: chip
            for gw, chip in actual_chip_timing.items()
            if chip in {Chip.FH, Chip.WC}
        }

        def _get_optimal_chip_timing_half(
            half_analyses: dict[int, GameweekAnalysis],
        ) -> None:
            """
            Finds the optimal Triple Captain and Bench Boost timing
            for a half of the season.

            Each gameweek is scored by the points that would be
            gained if the chip was played that gameweek. For Triple
            Captain, the chip bonus is the points the optimal
            captian scored. For Bench Boost, the chip bonus is the
            points left on the optimal bench.
            """
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
            if best_tc_gw is not None:
                optimal_chip_timing[best_tc_gw] = Chip.TC
            if best_bb_gw is not None:
                optimal_chip_timing[best_bb_gw] = Chip.BB

        first_half: dict[int, GameweekAnalysis] = {
            gw: a for gw, a in gw_analyses.items() if gw <= 19
        }
        second_half: dict[int, GameweekAnalysis] = {
            gw: a for gw, a in gw_analyses.items() if gw > 19
        }
        _get_optimal_chip_timing_half(first_half)
        if second_half:
            _get_optimal_chip_timing_half(second_half)

        return optimal_chip_timing

    def analyze_season(self) -> SeasonAnalysis:
        """Returns a SeasonAnalysis object from the raw gameweek data."""
        gw_analyses: dict[int, GameweekAnalysis] = {
            round: self.analyze_gameweek(round) for round in self._gameweeks
        }

        actual_chip_timing: dict[int, Chip] = self._get_actual_chip_timing()
        optimal_chip_timing: dict[int, Chip] = self._get_optimal_chip_timing(
            gw_analyses
        )

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
