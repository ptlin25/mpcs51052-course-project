import asyncio
import sys

from hindsight.data import fetch
from hindsight.models import Chip
from hindsight.analyze import (
    Analyzer,
    GameweekAnalysis,
    SeasonAnalysis,
    PlayerPoints,
)


HORIZONTAL_LINE = "=" * 80


def display_gameweek(analysis: SeasonAnalysis, round: int) -> str:
    gameweek: GameweekAnalysis = analysis.gameweek_analyses[round]

    captain: PlayerPoints | None = gameweek.captain
    captain_name: str = captain.player.name if captain is not None else ""
    captain_points: int = captain.points if captain is not None else 0
    chip_bonus: int = analysis.actual_chip_bonus_for(round)
    actual_points: int = gameweek.raw_points + captain_points + chip_bonus

    optimal_captain: PlayerPoints = gameweek.optimal_captain
    optimal_selection_chip_bonus: int = analysis.optimal_selection_chip_bonus_for(round)
    optimal_selection_points: int = (
        gameweek.optimal_raw_points
        + optimal_captain.points
        + optimal_selection_chip_bonus
    )

    header: list[str] = ["", "Total", "Starters", "Captain", "Chip"]
    data: list[list] = [
        ["Actual", actual_points, gameweek.raw_points, captain_points, chip_bonus],
        [
            "Optimal",
            optimal_selection_points,
            gameweek.optimal_raw_points,
            optimal_captain.points,
            optimal_selection_chip_bonus,
        ],
    ]

    summary: list[str] = []
    if chip := gameweek.active_chip:
        summary.append(f"{chip} played")

    summary.append("-" * 50)
    summary.append(
        f"{header[0]:<8} {header[1]:^5} = {header[2]:^8} + {header[3]:^7} + {header[4]:^4}"
    )
    summary.append("-" * 50)

    for row, total_points, raw_points, captain_b, chip_b in data:
        summary.append(
            f"{row:<8} {total_points:^5} = {raw_points:^8} + {captain_b:^7} + {chip_b:^4}"
        )

    summary.append(
        f"{optimal_selection_points - actual_points} points lost to selection mistakes"
    )

    changes: list[str] = []
    if captain != optimal_captain:
        bonus_multiplier: int = 2 if gameweek.active_chip == Chip.TC else 1
        changes.append(
            f"""Captain: {captain_name} -> {optimal_captain.player.name} [{captain_points * bonus_multiplier} -> {optimal_captain.points * bonus_multiplier} bonus points]"""
        )

    for bench, start in zip(gameweek.should_bench, gameweek.should_start):
        changes.append(
            f"Substitute: {bench.player.name} -> {start.player.name} [{bench.points} -> {start.points} points]"
        )

    return f"""{HORIZONTAL_LINE}
GW {gameweek.round}
{HORIZONTAL_LINE}
Summary:
{"\n".join(summary)}

Changes:
{"\n".join(changes)}
"""


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: hindsight <team_id>", file=sys.stderr)
        sys.exit(1)

    team_id: int = int(sys.argv[1])
    analyzer: Analyzer = Analyzer(await fetch(team_id))
    analysis: SeasonAnalysis = analyzer.analyze_season()
    print(f"total transfers cost {analysis.total_transfers_cost}")
    print(f"actual points no chips {analysis.actual_points_no_chips}")
    print(f"optimal points no chips {analysis.optimal_points_no_chips}")

    print()

    print(f"points from chips {analysis.actual_chip_bonus}")

    print(
        f"points from chips (optimal selection, same chip timing) {analysis.optimal_selection_chip_bonus}"
    )

    print(f"points from chips (optimal chip usage) {analysis.optimal_chip_bonus}")

    print(f"actual points {analysis.actual_total_points}")

    while True:
        try:
            raw = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        match raw.split():
            case []:
                continue
            case ["quit"]:
                break
            case ["gameweek", round]:
                print(display_gameweek(analysis, int(round)))
                pass


if __name__ == "__main__":
    asyncio.run(main())
