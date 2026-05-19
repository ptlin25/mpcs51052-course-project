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
        gameweek: GameweekAnalysis = self.analyze(points)
        assert {p.player.id for p in gameweek.optimal_starters} == expected_ids

    def test_total_squad_points_sums_all_15_players(self):
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


class TestAnalyzeSeason:
    def analyze(self, gameweeks: dict[int, Gameweek]) -> SeasonAnalysis:
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

        11 starters each score 5 points, so 55 raw points + 5 captain
        points = 60 points total before chip bonuses.
        """
        season: SeasonAnalysis = self.analyze(
            {
                1: make_gameweek(
                    BASE_POINTS, round=1, captain_multiplier=3, active_chip=Chip.TC
                ),
            }
        )
        assert season.actual_points_no_chips == 60

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
