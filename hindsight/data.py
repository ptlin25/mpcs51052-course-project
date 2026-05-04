import asyncio
from dataclasses import dataclass
import httpx
from typing import Any

from .models import Position, Chip, Player, Pick, Gameweek


NUM_GAMEWEEKS = 38


@dataclass(frozen=True)
class FPLData:
    players: dict[int, Player]
    gameweeks: list[Gameweek]


async def _fetch_player(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, player: Player
) -> None:
    url: str = f"https://fantasy.premierleague.com/api/element-summary/{player.id}/"

    async with sem:
        while True:
            response: httpx.Response = await client.get(url)
            if response.status_code == 429:
                print("Rate limit hit")
                await asyncio.sleep(1)
                continue
            break

        for match in response.json()["history"]:
            gameweek: int = match["round"]
            points: int = match["total_points"]
            player.history[gameweek - 1] += points


async def fetch_players(max_concurrency: int = 40) -> dict[int, Player]:

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
    async with httpx.AsyncClient() as client:
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
    url: str = (
        f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{round}/picks/"
    )

    async with sem:
        while True:
            response: httpx.Response = await client.get(url)
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                print("Rate limit hit")
                await asyncio.sleep(1)
                continue

            try:
                data: dict[str, Any] = response.json()
                active_chip: Chip | None = data["active_chip"]
                points: int = data["entry_history"]["points"]
                points_on_bench: int = data["entry_history"]["points_on_bench"]

                picks: list[Pick] = []
                for pick in data["picks"]:
                    player_id = pick["element"]
                    picks.append(
                        Pick(player=players[player_id], multiplier=pick["multiplier"])
                    )
                break
            except KeyError:
                continue

    return Gameweek(round, active_chip, points, points_on_bench, picks)


async def fetch_gameweeks(
    team_id: int, players: dict[int, Player], max_concurrency: int = 40
) -> list[Gameweek]:
    sem: asyncio.Semaphore = asyncio.Semaphore(max_concurrency)
    async with httpx.AsyncClient() as client:
        tasks: list[asyncio.Task[Gameweek | None]] = []
        async with asyncio.TaskGroup() as tg:
            for round in range(1, NUM_GAMEWEEKS + 1):
                tasks.append(
                    tg.create_task(
                        _fetch_gameweek(client, sem, team_id, round, players)
                    )
                )

    return sorted(
        [r for t in tasks if (r := t.result()) is not None], key=lambda gw: gw.round
    )


async def fetch_all(team_id: int) -> FPLData:
    players = await fetch_players()
    gameweeks = await fetch_gameweeks(team_id, players)
    return FPLData(players, gameweeks)
