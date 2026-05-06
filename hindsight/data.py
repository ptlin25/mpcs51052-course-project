import asyncio
import httpx
from dataclasses import dataclass
from typing import Any

from .models import Position, Chip, Player, Pick, Gameweek


NUM_GAMEWEEKS = 38


@dataclass(frozen=True)
class FPLData:
    players: dict[int, Player]
    gameweeks: dict[int, Gameweek]


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, max_retries: int = 3
) -> httpx.Response:
    """
    GET url, retrying on timeouts and 429s with exponential backoff.

    Raises the underlying exception or HTTPStatusError after max_retries attempts.
    """
    delay: float = 1.0
    for attempt in range(max_retries + 1):
        try:
            response: httpx.Response = await client.get(url)
        except httpx.TimeoutException:
            # raise the exception if this was the last retry
            if attempt == max_retries:
                raise
            # retry
            print(f"Request to {url} timed out, retrying in {delay:.0f}s")
            await asyncio.sleep(delay)
            delay *= 2
            continue
        if response.status_code == 429:
            # raise the exception if this was the last retry
            if attempt == max_retries:
                response.raise_for_status()
            # retry
            print(f"Rate limit hit, retrying in {delay:.0f}s")
            await asyncio.sleep(delay)
            delay *= 2
            continue
        # return the response if GET was successful
        return response
    # the loop either returns a response or raises an exception, this is unreachable
    assert False, "unreachable"


async def _fetch_player(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, player: Player
) -> None:
    """Fetch and populate player's per-gameweek point history in place."""
    url: str = f"https://fantasy.premierleague.com/api/element-summary/{player.id}/"

    async with sem:
        response: httpx.Response = await _get_with_retry(client, url)

        for match in response.json()["history"]:
            gameweek: int = match["round"]
            points: int = match["total_points"]
            player.history[gameweek - 1] += points


async def fetch_players(max_concurrency: int = 40) -> dict[int, Player]:
    """Fetch all FPL players and their per-gameweek point history, keyed by player ID."""
    players: dict[int, Player] = {}
    bootstrap_url: str = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response: httpx.Response = httpx.get(bootstrap_url)

    for element in response.json()["elements"]:
        players[element["id"]] = Player(
            id=element["id"],
            name=f"{element['first_name']} {element['second_name']}",
            position=Position(element["element_type"]),
            history=[0] * NUM_GAMEWEEKS,
        )

    sem: asyncio.Semaphore = asyncio.Semaphore(max_concurrency)
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with asyncio.TaskGroup() as tg:
            for player in players.values():
                tg.create_task(_fetch_player(client, sem, player))

    return players


async def _fetch_gameweek(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    team_id: int,
    round: int,
    players: dict[int, Player],
) -> Gameweek | None:
    """
    Fetch picks and score data for team_id in the given round.

    Returns None if the round has not been played yet (404).
    """
    url: str = (
        f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{round}/picks/"
    )
    # use semaphore to cap max concurrency
    async with sem:
        response: httpx.Response = await _get_with_retry(client, url)
        if response.status_code == 404:
            return None

        data: dict[str, Any] = response.json()
        active_chip: Chip | None = data["active_chip"]
        points: int = data["entry_history"]["points"]
        points_on_bench: int = data["entry_history"]["points_on_bench"]

        picks: list[Pick] = []
        for pick in data["picks"]:
            player_id = pick["element"]
            picks.append(Pick(player=players[player_id], multiplier=pick["multiplier"]))

    return Gameweek(round, active_chip, points, points_on_bench, picks)


async def fetch_gameweeks(
    team_id: int, players: dict[int, Player], max_concurrency: int = 40
) -> dict[int, Gameweek]:
    """Fetch picks and score data for team_id for all rounds"""
    sem: asyncio.Semaphore = asyncio.Semaphore(max_concurrency)
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks: list[asyncio.Task[Gameweek | None]] = []
        async with asyncio.TaskGroup() as tg:
            for round in range(1, NUM_GAMEWEEKS + 1):
                tasks.append(
                    tg.create_task(
                        _fetch_gameweek(client, sem, team_id, round, players)
                    )
                )

    return {gw.round: gw for t in tasks if (gw := t.result()) is not None}


async def fetch_all(team_id: int) -> FPLData:
    """Fetch all player and gameweek data for the given team."""
    players = await fetch_players()
    gameweeks = await fetch_gameweeks(team_id, players)
    return FPLData(players, gameweeks)
