import asyncio
import httpx
from requests import Response

NUM_GAMEWEEKS = 38  # testing
TEAM_ID = 2926821

from models import Position, Chip, Player, Pick, Gameweek


def fetch_players() -> dict[int, Player]:
    players: dict[int, Player] = {}
    response: Response = httpx.get(
        "https://fantasy.premierleague.com/api/bootstrap-static/"
    )
    for element in response.json()["elements"]:
        players[element["id"]] = Player(
            id=element["id"],
            name=f"{element['first_name']} {element['second_name']}",
            position=Position(element["element_type"]),
            history=[0] * NUM_GAMEWEEKS,
        )

    for id, player in players.items():
        response: Response = httpx.get(
            f"https://fantasy.premierleague.com/api/element-summary/{id}/"
        )
        if response.status_code == 429:
            print("rate limit hit")

        for match in response.json()["history"]:
            gameweek: int = match["round"]
            points: int = match["total_points"]
            player.history[gameweek - 1] += points

    return players


def fetch_gameweeks(team_id: int) -> list[Gameweek]:
    gameweeks: list[Gameweek] = []
    for gw in range(1, NUM_GAMEWEEKS + 1):
        response: Response = httpx.get(
            f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"
        )
        if response.status_code != 200:
            break

        active_chip: Chip | None = response.json().get("active_chip")
        points: int = response.json().get("entry_history").get("points")
        points_on_bench: int = (
            response.json().get("entry_history").get("points_on_bench")
        )

        picks: list[Pick] = []
        for pick in response.json().get("picks"):
            picks.append(
                Pick(player_id=pick.get("element"), multiplier=pick.get("multiplier"))
            )

        gameweeks.append(Gameweek(gw, active_chip, points, points_on_bench, picks))

    return gameweeks
