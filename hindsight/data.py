import asyncio
from collections.abc import Coroutine
import httpx
import time
from typing import Any

from .models import Position, Chip, Player, Pick, Gameweek


NUM_GAMEWEEKS = 38
TEAM_ID = 2926821  # temp


async def _fetch_player(client: httpx.AsyncClient, player: Player) -> None:
    url: str = f"https://fantasy.premierleague.com/api/element-summary/{player.id}/"

    while True:
        response: httpx.Response = await client.get(url)
        if response.status_code == 429:
            print("rate limit hit")
            await asyncio.sleep(1)
            continue
        break

    for match in response.json()["history"]:
        gameweek: int = match["round"]
        points: int = match["total_points"]
        player.history[gameweek - 1] += points


async def fetch_players(batch_size: int = 20) -> dict[int, Player]:
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

    player_list = list(players.values())
    async with httpx.AsyncClient() as client:
        for i in range(0, len(player_list), batch_size):
            tasks: list[Coroutine[Any, Any, None]] = [
                _fetch_player(client, player)
                for player in player_list[i : i + batch_size]
            ]
            await asyncio.gather(*tasks)

    return players


async def _fetch_gameweek(
    client: httpx.AsyncClient, team_id: int, round: int
) -> Gameweek | None:
    url: str = (
        f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{round}/picks/"
    )

    while True:
        response: httpx.Response = await client.get(url)
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            print("rate limit hit")
            await asyncio.sleep(1)
            continue

        try:
            data: dict[str, Any] = response.json()
            active_chip: Chip | None = data["active_chip"]
            points: int = data["entry_history"]["points"]
            points_on_bench: int = data["entry_history"]["points_on_bench"]

            picks: list[Pick] = []
            for pick in data["picks"]:
                picks.append(
                    Pick(player_id=pick["element"], multiplier=pick["multiplier"])
                )
            break
        except KeyError:
            continue

    return Gameweek(round, active_chip, points, points_on_bench, picks)


async def fetch_gameweeks(team_id: int, batch_size: int = 20) -> list[Gameweek]:
    gameweeks: list[Gameweek] = []
    async with httpx.AsyncClient() as client:
        for i in range(1, NUM_GAMEWEEKS + 1, batch_size):
            tasks: list[Coroutine[Any, Any, Gameweek | None]] = [
                _fetch_gameweek(client, team_id, round)
                for round in range(i, i + batch_size)
            ]
            gameweeks += [gw for gw in await asyncio.gather(*tasks) if gw is not None]

    return sorted(gameweeks, key=lambda gw: gw.round)
