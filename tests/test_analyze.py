import pytest

from hindsight.models import Chip, Gameweek, Pick, Player, Position
from hindsight.analyze import Analyzer, ChipUsage, GameweekAnalysis, SeasonAnalysis

ALL_STARTERS = set(range(1, 12))
GKP_BENCH, DEF_BENCH, MID_BENCH, FWD_BENCH = 12, 13, 14, 15
CAPTAIN = 1

PLAYER_POSITIONS = {
    1: Position.GKP,
    2: Position.DEF,
    3: Position.DEF,
    4: Position.DEF,
    5: Position.DEF,
    6: Position.MID,
    7: Position.MID,
    8: Position.MID,
    9: Position.MID,
    10: Position.FWD,
    11: Position.FWD,
    12: Position.GKP,
    13: Position.DEF,
    14: Position.MID,
    15: Position.FWD,
}

# starters each score 5, bench players each score 0
BASE_POINTS = {i: 5 for i in ALL_STARTERS} | {
    i: 0 for i in {GKP_BENCH, DEF_BENCH, MID_BENCH, FWD_BENCH}
}


def make_gameweek(
    points: dict[int, int],
    captain_multiplier: int = 2,
    round: int = 1,
    active_chip: Chip | None = None,
    transfers_cost: int = 0,
) -> Gameweek:
    """
    Helper function that returns a Gameweek object.

    Creates 15 players with ids 1-15. Players 1-11 are starters,
    and player 1 is the captain. Players 1 and 12 are GKPs;
    players 2, 3, 4, 5, and 13 are DEFs; players 6, 7, 8, 9, and
    14 are MIDs; players 10, 11, and 15 are FWDs.

    Args:
    - points: dict mapping id to points scored.
    - captain_multiplier: captain's point multiplier
      (1=no captain, 2=regular captain, 3=Triple Captain played)
    - round: gameweek round number
    - active_chip: chip played this gameweek
    - transfers_cost: cost of transfers this gameweek
    """
    picks = []
    for i in range(1, 16):
        player = Player(
            id=i,
            name=f"Player{i}",
            position=PLAYER_POSITIONS[i],
            history=[0] * (round - 1) + [points[i]],
        )
        multiplier = captain_multiplier if i == 1 else (1 if i <= 11 else 0)
        picks.append(Pick(player, multiplier, i))
    return Gameweek(round, active_chip, transfers_cost, picks)


class TestAnalyzeGameweek:
    def analyze(self, points: dict[int, int], **kwargs) -> GameweekAnalysis:
        """Helper function that returns a single GameweekAnalysis object."""
        return Analyzer({1: make_gameweek(points, **kwargs)}).analyze_gameweek(1)

    @pytest.mark.parametrize(
        "points,expected_ids",
        [
            pytest.param(
                # all starters outscore bench (no swaps)
                {
                    1: 10,
                    2: 10,
                    3: 10,
                    4: 10,
                    5: 10,
                    6: 10,
                    7: 10,
                    8: 10,
                    9: 10,
                    10: 10,
                    11: 10,
                    12: 0,
                    13: 0,
                    14: 0,
                    15: 0,
                },
                ALL_STARTERS,
                id="all_starters_optimal",
            ),
            pytest.param(
                # bench GKP (12) outscores starting GKP (1)
                {
                    1: 1,
                    2: 6,
                    3: 4,
                    4: 5,
                    5: 8,
                    6: 9,
                    7: 5,
                    8: 7,
                    9: 6,
                    10: 5,
                    11: 5,
                    12: 3,
                    13: 0,
                    14: 0,
                    15: 0,
                },
                ALL_STARTERS - {1} | {GKP_BENCH},
                id="bench_gkp_optimal",
            ),
            pytest.param(
                # bench FWD (15) wins mandatory FWD slot; bench MID (14) and starter FWD (10) fill flex
                {
                    1: 5,
                    2: 8,
                    3: 7,
                    4: 6,
                    5: 1,
                    6: 8,
                    7: 7,
                    8: 6,
                    9: 5,
                    10: 8,
                    11: 1,
                    12: 0,
                    13: 1,
                    14: 5,
                    15: 9,
                },
                ALL_STARTERS - {5, 11} | {MID_BENCH, FWD_BENCH},
                id="optimal_starters_changes_formation",
            ),
            pytest.param(
                # min 3 DEF still required, flex goes to MID/FWD
                {
                    1: 5,
                    2: 1,
                    3: 1,
                    4: 1,
                    5: 0,
                    6: 5,
                    7: 5,
                    8: 5,
                    9: 5,
                    10: 10,
                    11: 10,
                    12: 0,
                    13: 0,
                    14: 5,
                    15: 4,
                },
                ALL_STARTERS - {5} | {MID_BENCH},
                id="min_3_defenders",
            ),
        ],
    )
    def test_optimal_starters_selects_highest_scoring_valid_11(
        self, points, expected_ids
    ):
        """Test that optimal_starters makes the correct optimizations."""
        gameweek: GameweekAnalysis = self.analyze(points)
        assert {p.player.id for p in gameweek.optimal_starters} == expected_ids

    def test_total_squad_points_sums_all_15_players(self):
        """Test that total_squad_points sums points of the entire squad."""
        gameweek: GameweekAnalysis = self.analyze({i: 1 for i in range(1, 16)})
        assert gameweek.total_squad_points == 15

    def test_actual_captain_is_none(self):
        """
        Test that captain is None when there is no captain.

        If the captain and vice captain are auto-subbed out,
        no player should be the captain.
        """
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS, captain_multiplier=1)
        assert gameweek.captain is None

    def test_triple_captain_has_correct_captain(self):
        """Test that captain is correct when Triple Captain is played."""
        gameweek: GameweekAnalysis = self.analyze(
            BASE_POINTS, captain_multiplier=3, active_chip=Chip.TC
        )
        assert gameweek.captain.player.id == CAPTAIN

    def test_optimal_captain_is_player_with_highest_points(self):
        """Test that the optimal captain is the highest scoring player."""
        gameweek: GameweekAnalysis = self.analyze({**BASE_POINTS, 2: 10})
        assert gameweek.optimal_captain.player.id == 2

    def test_starters_are_players_in_positions_1_through_11(self):
        """Test that the actual starters are in pick positions 1-11."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert {p.player.id for p in gameweek.starters} == ALL_STARTERS

    def test_active_chip_is_recorded_on_analysis(self):
        """Test that the active_chip is passed through to GameweekAnalysis."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS, active_chip=Chip.BB)
        assert gameweek.active_chip == Chip.BB

    def test_transfers_cost_is_recorded_on_analysis(self):
        """Test that the transfers_cost is passed through to GameweekAnalysis."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS, transfers_cost=8)
        assert gameweek.transfers_cost == 8

    def test_captain_points_is_zero_when_no_captain(self):
        """Test that captain_points is 0 when no player has a multiplier >= 2."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS, captain_multiplier=1)
        assert gameweek.captain_points == 0

    def test_captain_points_returns_the_captains_score(self):
        """Test that captain_points equals the captain's actual points scored."""
        gameweek: GameweekAnalysis = self.analyze({**BASE_POINTS, CAPTAIN: 7})
        assert gameweek.captain_points == 7

    def test_raw_points_sums_the_11_actual_starters(self):
        """Test that raw_points is the total points of the starting 11.

        11 starters each score 5, so raw_points should be 55.
        """
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert gameweek.raw_points == 55

    def test_actual_points_no_chips_is_raw_points_plus_captain_points(self):
        """Test that actual_points_no_chips = raw_points + captain_points.

        11 starters each score 5 (55 raw), captain scores 5 bonus = 60.
        """
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert gameweek.actual_points_no_chips == 60

    def test_optimal_points_no_chips_uses_best_selection_and_captain(self):
        """Test that optimal_points_no_chips uses the optimal XI and optimal captain.

        Player 2 (DEF) scores 10, all others score 5 or 0. Optimal XI keeps
        all actual starters (bench scores 0). Optimal captain is player 2 (10
        points). optimal_raw = 10 + 10*5 = 60, plus captain bonus of 10 = 70.
        """
        gameweek: GameweekAnalysis = self.analyze({**BASE_POINTS, 2: 10})
        assert gameweek.optimal_points_no_chips == 70

    def test_points_on_actual_bench_is_total_minus_raw(self):
        """Test that points_on_actual_bench = total_squad_points - raw_points."""
        points = {**BASE_POINTS, GKP_BENCH: 3, DEF_BENCH: 2, MID_BENCH: 1, FWD_BENCH: 4}
        gameweek: GameweekAnalysis = self.analyze(points)
        assert gameweek.points_on_actual_bench == 10

    def test_points_on_optimal_bench_is_total_minus_optimal_raw(self):
        """Test that points_on_optimal_bench = total_squad_points - optimal_raw_points."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert gameweek.points_on_optimal_bench == (
            gameweek.total_squad_points - gameweek.optimal_raw_points
        )

    def test_should_bench_is_empty_when_starters_are_optimal(self):
        """Test that should_bench is empty when the actual XI is already optimal."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert gameweek.should_bench == []

    def test_should_start_is_empty_when_starters_are_optimal(self):
        """Test that should_start is empty when the actual XI is already optimal."""
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert gameweek.should_start == []

    def test_should_bench_lists_starters_that_scored_below_a_bench_player(self):
        """Test that should_bench contains the suboptimal starter.

        Bench MID (14) scores 8, starter FWD (11) scores 0. Player 11
        should have been benched in favour of player 14.
        """
        gameweek: GameweekAnalysis = self.analyze({**BASE_POINTS, 11: 0, 14: 8})
        assert {p.player.id for p in gameweek.should_bench} == {11}

    def test_should_start_lists_bench_players_that_outscored_a_starter(self):
        """Test that should_start contains the bench player who should have started.

        Bench MID (14) scores 8, starter FWD (11) scores 0. Player 14
        should have started in place of player 11.
        """
        gameweek: GameweekAnalysis = self.analyze({**BASE_POINTS, 11: 0, 14: 8})
        assert {p.player.id for p in gameweek.should_start} == {14}

    def test_optimal_captain_keeps_actual_captain_on_tied_score(self):
        """Test that optimal_captain returns the actual captain when scores are tied.

        All starters score 5, so every optimal starter ties for highest. The
        actual captain (player 1) should be returned rather than an arbitrary
        high scorer.
        """
        gameweek: GameweekAnalysis = self.analyze(BASE_POINTS)
        assert gameweek.optimal_captain.player.id == CAPTAIN


class TestAnalyzeSeason:
    def analyze(self, gameweeks: dict[int, Gameweek]) -> SeasonAnalysis:
        """Helper function that returns a SeasonAnalysis object."""
        return Analyzer(gameweeks).analyze_season()

    def test_total_transfers_cost_sums_all_gameweeks(self):
        """Test that total_transfers_cost sums the transfers_cost of all gameweeks"""
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(BASE_POINTS, round=1, transfers_cost=4),
                2: make_gameweek(BASE_POINTS, round=2, transfers_cost=8),
            }
        )
        assert season.total_transfers_cost == 12

    def test_actual_points_no_chips_sums_starters_and_captain(self):
        """
        Test that actual_points_no_chips is correct.

        Test that actual_points_no_chips is equal to the total actual
        points without chip bonuses i.e. total points with the actual
        starters and actual captain.

        Each gameweek, 11 starters each score 5 points, so 55 raw points + 5 captain
        points = 60 points total per gameweek -> 120 points total.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    BASE_POINTS, round=1, captain_multiplier=3, active_chip=Chip.TC
                ),
                2: make_gameweek(BASE_POINTS, round=2),
            }
        )
        assert season.actual_points_no_chips == 120

    def test_optimal_points_no_chips_uses_best_selection(self):
        """
        Test that optimal_points_no_chips uses the best selection.

        11 starters each score 5 points and the bench FWD scores 20.
        The optimal selection subs the bench FWD for any of the
        starters and captains the bench FWD. 10 starters each score 5
        points and the captain scores 20, so 70 raw points + 20
        captain points = 90 points total before chip bonuses.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, 15: 20},
                    round=1,
                    captain_multiplier=3,
                    active_chip=Chip.TC,
                ),
            }
        )
        assert season.optimal_points_no_chips == 90

    def test_actual_chip_usage_records_chips_as_played(self):
        """
        Test that actual_chip_usage records the actual chip usage.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(BASE_POINTS, round=1, active_chip=Chip.FH),
                2: make_gameweek(BASE_POINTS, round=2, active_chip=Chip.BB),
            }
        )
        assert season.actual_chip_usage == {
            1: ChipUsage(Chip.FH, 0),
            2: ChipUsage(Chip.BB, 0),
        }

    def test_actual_tc_chip_bonus(self):
        """Test actual TC bonus is equal to the captain's points."""
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, CAPTAIN: 10}, round=1, active_chip=Chip.TC
                ),
            }
        )
        assert season.actual_chip_usage == {1: ChipUsage(Chip.TC, 10)}

    def test_actual_bb_chip_bonus(self):
        """Test actual BB bonus is equal to the points on bench."""
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, 12: 2, 15: 4}, round=1, active_chip=Chip.BB
                ),
            }
        )
        assert season.actual_chip_usage == {1: ChipUsage(Chip.BB, 6)}

    def test_optimal_selection_chip_usage_keeps_actual_timing(self):
        """
        Test that optimal_selection_chip_usage keeps actual timing.

        In this test, Bench Boost is used gw 2, but the optimal usage is
        in gw 1. The optimal_selection_chip_usage shoud record Bench
        Boost played gw 2.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek({**BASE_POINTS, 15: 3}, round=1),
                2: make_gameweek({**BASE_POINTS, 15: 1}, round=2, active_chip=Chip.BB),
            }
        )
        assert season.optimal_selection_chip_usage == {2: ChipUsage(Chip.BB, 1)}

    def test_optimal_chip_usage_reassigns_tc_and_bb_to_best_gameweeks(self):
        """
        Test that optimal_chip_usage reassigns TC and BB.

        Triple Captain played gw 1 for 5 points and Bench Boost played
        gw 2 for 0 points. The optimal timing is Triple Captain played
        gw 2 for 10 points and Bench Boost played gw 1 for 1 point.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek({**BASE_POINTS, 15: 1}, round=1, active_chip=Chip.TC),
                2: make_gameweek(
                    {**BASE_POINTS, CAPTAIN: 10}, round=2, active_chip=Chip.BB
                ),
            }
        )
        assert season.optimal_chip_usage == {
            1: ChipUsage(Chip.BB, 1),
            2: ChipUsage(Chip.TC, 10),
        }

    def test_actual_chip_bonus_sums_bonuses_across_all_gameweeks(self):
        """Test that actual_chip_bonus is the sum of all gameweek chip bonuses.

        TC played gw 1 (captain scores 10, bonus=10), BB played gw 2
        (bench GKP scores 6, bonus=6). actual_chip_bonus = 10 + 6 = 16.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, CAPTAIN: 10}, round=1, active_chip=Chip.TC
                ),
                2: make_gameweek(
                    {**BASE_POINTS, GKP_BENCH: 6}, round=2, active_chip=Chip.BB
                ),
            }
        )
        assert season.actual_chip_bonus == 16

    def test_actual_total_points_adds_chip_bonus_and_subtracts_transfers(self):
        """Test that actual_total_points = actual_points_no_chips + chip bonus - transfers.

        11 starters score 5 (55 raw) + 5 captain bonus = 60 points no chips.
        TC bonus = 5 (captain scored 5). Transfers cost 4.
        actual_total_points = 60 + 5 - 4 = 61.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    BASE_POINTS, round=1, active_chip=Chip.TC, transfers_cost=4
                ),
            }
        )
        assert season.actual_total_points == 61

    def test_optimal_selection_total_points_does_not_subtract_transfers(self):
        """Test that optimal_selection_total_points omits the transfers cost.

        actual_total_points subtracts transfers; the optimal variants do not,
        since they represent the ceiling regardless of transfer decisions.
        """
        season: SeasonAnalysis = self.analyze(
            {1: make_gameweek(BASE_POINTS, round=1, transfers_cost=4)}
        )
        assert season.optimal_selection_total_points == season.optimal_points_no_chips
        assert season.actual_total_points == season.actual_points_no_chips - 4

    def test_optimal_total_points_uses_optimal_chip_bonus(self):
        """Test that optimal_total_points = optimal_points_no_chips + optimal_chip_bonus."""
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, CAPTAIN: 10}, round=1, active_chip=Chip.TC
                ),
            }
        )
        assert season.optimal_total_points == (
            season.optimal_points_no_chips + season.optimal_chip_bonus
        )

    def test_actual_chip_bonus_for_returns_zero_when_no_chip_played(self):
        """Test that actual_chip_bonus_for returns 0 for a gameweek without a chip."""
        season: SeasonAnalysis = self.analyze({1: make_gameweek(BASE_POINTS, round=1)})
        assert season.actual_chip_bonus_for(1) == 0

    def test_actual_chip_bonus_for_returns_bonus_for_chip_gameweek(self):
        """Test that actual_chip_bonus_for returns the chip bonus for that gameweek."""
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, CAPTAIN: 8}, round=1, active_chip=Chip.TC
                ),
            }
        )
        assert season.actual_chip_bonus_for(1) == 8

    def test_optimal_selection_tc_bonus_uses_optimal_captain(self):
        """Test that optimal_selection_chip_usage TC bonus uses the optimal captain.

        Actual captain (player 1) scores 5; player 2 (DEF) scores 10 and
        is the optimal captain. actual TC bonus = 5, optimal_selection TC
        bonus = 10.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek({**BASE_POINTS, 2: 10}, round=1, active_chip=Chip.TC),
            }
        )
        assert season.actual_chip_usage == {1: ChipUsage(Chip.TC, 5)}
        assert season.optimal_selection_chip_usage == {1: ChipUsage(Chip.TC, 10)}

    def test_optimal_selection_bb_bonus_uses_optimal_bench(self):
        """Test that optimal_selection_chip_usage BB bonus uses the optimal bench.

        Bench MID (14) scores 8 and starter FWD (11) scores 0. The actual BB
        bonus includes player 14's 8 points (on the actual bench). The optimal
        selection puts player 14 in the XI, so the optimal bench holds player
        11 (0 points) instead — giving a BB bonus of 0.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    {**BASE_POINTS, 11: 0, MID_BENCH: 8},
                    round=1,
                    active_chip=Chip.BB,
                ),
            }
        )
        assert season.actual_chip_usage == {1: ChipUsage(Chip.BB, 8)}
        assert season.optimal_selection_chip_usage == {1: ChipUsage(Chip.BB, 0)}
