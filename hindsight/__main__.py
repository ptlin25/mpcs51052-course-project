import asyncio
import sys

from hindsight.data import fetch, NUM_GAMEWEEKS
from hindsight.models import Chip
from hindsight.analyze import (
    Analyzer,
    GameweekAnalysis,
    SeasonAnalysis,
    PlayerPoints,
)


HORIZONTAL_LINE: str = "=" * 100

type ChipMap = dict[tuple[Chip, int], tuple[int, int]]


def clear_console() -> None:
    print("\033[2J\033[H")


def format_lineup(gameweek: GameweekAnalysis) -> str:
    """Side-by-side table of actual vs optimal starting 11, sorted by position."""
    col_w = 38

    def sort_key(pp: PlayerPoints) -> tuple[int, int, str]:
        return (pp.player.position.value, -pp.points, pp.player.name)

    actual: list[PlayerPoints] = sorted(gameweek.starters, key=sort_key)
    optimal: list[PlayerPoints] = sorted(gameweek.optimal_starters, key=sort_key)

    header: str = f"{'Actual':<{col_w}} {'Pts':>3}  {'Optimal':<{col_w}} {'Pts':>3}"
    sep: str = "-" * (col_w * 2 + 10)
    rows: list[str] = [header, sep]
    for a, o in zip(actual, optimal):
        a_label: str = f"{a.player.name} ({a.player.position.name})"
        o_label: str = f"{o.player.name} ({o.player.position.name})"
        rows.append(
            f"{a_label:<{col_w}} {a.points:>3}  {o_label:<{col_w}} {o.points:>3}"
        )
    return "\n".join(rows)


def format_chip_usage_summary(analysis: SeasonAnalysis) -> str:
    """Chip timing and bonus comparison across actual, optimal selection, and optimal chip timing."""

    def chip_map(usage_dict: dict) -> ChipMap:
        return {
            (u.chip, 1 if gw <= 19 else 2): (gw, u.chip_bonus)
            for gw, u in usage_dict.items()
        }

    actual_map: ChipMap = chip_map(analysis.actual_chip_usage)
    opt_sel_map: ChipMap = chip_map(analysis.optimal_selection_chip_usage)
    opt_chip_map: ChipMap = chip_map(analysis.optimal_chip_usage)

    all_keys: set[tuple[Chip, int]] = set(actual_map) | set(opt_chip_map)
    if not all_keys:
        return "No chips played."

    chip_order: dict[Chip, int] = {Chip.TC: 0, Chip.BB: 1, Chip.FH: 2, Chip.WC: 3}
    sorted_keys: list[tuple[Chip, int]] = sorted(
        all_keys, key=lambda k: (chip_order[k[0]], k[1])
    )

    def fmt_entry(m: ChipMap, key: tuple[Chip, int]) -> str:
        if key not in m:
            return "-"
        gw, bonus = m[key]
        return f"GW{gw:2d} ({bonus:+d})"

    col_w: int = 13
    label_w: int = 11
    sep: str = "-" * (label_w + col_w * 3 + 6)
    rows: list[str] = [
        "Chip Usage",
        sep,
        f"{'':>{label_w}}  {'Actual':^{col_w}}  {'Opt (sel)':^{col_w}}  {'Opt (chip)':^{col_w}}",
        sep,
        *[
            (
                f"{f'{key[0]} H{key[1]}':<{label_w}}  "
                f"{fmt_entry(actual_map, key):^{col_w}}  "
                f"{fmt_entry(opt_sel_map, key):^{col_w}}  "
                f"{fmt_entry(opt_chip_map, key):^{col_w}}"
            )
            for key in sorted_keys
        ],
        sep,
        (
            f"{'Total':<{label_w}}  "
            f"{analysis.actual_chip_bonus:^{col_w}}  "
            f"{analysis.optimal_selection_chip_bonus:^{col_w}}  "
            f"{analysis.optimal_chip_bonus:^{col_w}}"
        ),
        sep,
    ]
    return "\n".join(rows)


def format_season_summary(analysis: SeasonAnalysis) -> str:
    """Summary table comparing actual, optimal-selection, and optimal-chip-timing points."""
    label_w: int = 26
    header: str = f"{'':>{label_w}} {'Actual':>8} {'Opt (sel)':>10} {'Opt (chip)':>11}"
    sep: str = "-" * (label_w + 32)
    rows: list[str] = [
        "Season Summary",
        sep,
        header,
        sep,
        (
            f"{'Points (no chips)':<{label_w}} "
            f"{analysis.actual_points_no_chips:>8} "
            f"{analysis.optimal_points_no_chips:>10} "
            f"{analysis.optimal_points_no_chips:>11}"
        ),
        (
            f"{'Chip bonus':<{label_w}} "
            f"{analysis.actual_chip_bonus:>8} "
            f"{analysis.optimal_selection_chip_bonus:>10} "
            f"{analysis.optimal_chip_bonus:>11}"
        ),
        (
            f"{'Transfer cost':<{label_w}} "
            f"{-analysis.total_transfers_cost:>8} "
            f"{-analysis.total_transfers_cost:>10} "
            f"{-analysis.total_transfers_cost:>11}"
        ),
        sep,
        (
            f"{'Total':<{label_w}} "
            f"{analysis.actual_total_points:>8} "
            f"{analysis.optimal_selection_total_points:>10} "
            f"{analysis.optimal_total_points:>11}"
        ),
        sep,
    ]
    return "\n".join(rows)


def format_gameweek_summary(analysis: SeasonAnalysis, round: int) -> str:
    """Formatted breakdown of a single gameweek: lineup, points summary, and suggested changes."""
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

    sep: str = "-" * 50
    rows: str = [
        HORIZONTAL_LINE,
        f"GW {gameweek.round}",
        HORIZONTAL_LINE,
        "Lineup:",
        format_lineup(gameweek),
        "",
        "Summary:",
        *([f"{gameweek.active_chip} played"] if gameweek.active_chip else []),
        sep,
        f"{'':8} {'Total':^5} = {'Starters':^8} + {'Captain':^7} + {'Chip':^4}",
        sep,
        (
            f"{'Actual':<8} {actual_points:^5} = "
            f"{gameweek.raw_points:^8} + "
            f"{captain_points:^7} + "
            f"{chip_bonus:^4}"
        ),
        (
            f"{'Optimal':<8} {optimal_selection_points:^5} = "
            f"{gameweek.optimal_raw_points:^8} + "
            f"{optimal_captain.points:^7} + "
            f"{optimal_selection_chip_bonus:^4}"
        ),
        f"{optimal_selection_points - actual_points} points lost to selection mistakes",
        "",
        "Changes:",
    ]

    if captain != optimal_captain:
        bonus_multiplier: int = 2 if gameweek.active_chip == Chip.TC else 1
        rows.append(
            f"Captain: {captain_name} -> {optimal_captain.player.name} "
            f"[{captain_points * bonus_multiplier} -> {optimal_captain.points * bonus_multiplier} bonus points]"
        )
    for bench, start in zip(gameweek.should_bench, gameweek.should_start):
        rows.append(
            f"Substitute: {bench.player.name} -> {start.player.name} "
            f"[{bench.points} -> {start.points} points]"
        )

    return "\n".join(rows)


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: hindsight <team_id>", file=sys.stderr)
        sys.exit(1)

    team_id: int = int(sys.argv[1])
    analyzer: Analyzer = Analyzer(await fetch(team_id))
    analysis: SeasonAnalysis = analyzer.analyze_season()
    print(format_season_summary(analysis))

    while True:
        try:
            raw = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        match raw.split():
            case []:
                continue
            case ["quit"] | ["q"]:
                break
            case ["gameweek", round] | ["gw", round]:
                round: int = int(round)
                if round <= 0 or round > NUM_GAMEWEEKS:
                    print("Please enter a valid gameweek round [1-38].")
                    continue
                elif round > len(analysis.gameweek_analyses):
                    print("This gameweek has not occurred yet.")
                    continue
                clear_console()
                print(format_gameweek_summary(analysis, int(round)))
            case ["season"]:
                clear_console()
                print(format_season_summary(analysis))
            case ["chip"]:
                clear_console()
                print(format_chip_usage_summary(analysis))


if __name__ == "__main__":
    asyncio.run(main())
