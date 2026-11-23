"""Server MCP remote untuk data publik Chess.com.

Jalan di lokal:   python server.py   -> http://localhost:8000/mcp
Di Render/Railway port diambil otomatis dari env PORT.
Tidak perlu login/password: semua data diambil dari API publik Chess.com.
"""

import os
import re
from datetime import datetime, timezone

import httpx
from mcp.server.mcpserver import MCPServer

API = "https://api.chess.com/pub"
HEADERS = {"User-Agent": "chesscom-mcp/1.0 (personal Claude connector)"}

mcp = MCPServer(
    name="chesscom",
    instructions=(
        "Ambil data publik Chess.com: profil, rating, arsip game, dan PGN. "
        "Pakai username Chess.com (bukan nama tampilan)."
    ),
)


async def _get(url: str) -> dict:
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
        r = await client.get(url)
        if r.status_code == 404:
            raise ValueError("Data tidak ditemukan. Cek lagi username-nya.")
        r.raise_for_status()
        return r.json()


def _clean(username: str) -> str:
    u = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{3,25}", u):
        raise ValueError("Format username tidak valid.")
    return u


@mcp.tool(description="Profil dan rating (rapid, blitz, bullet, daily, puzzle) pemain Chess.com.")
async def get_player(username: str) -> dict:
    u = _clean(username)
    profile = await _get(f"{API}/player/{u}")
    stats = await _get(f"{API}/player/{u}/stats")

    ratings = {}
    for key, val in stats.items():
        if key.startswith("chess_") and isinstance(val, dict):
            ratings[key.removeprefix("chess_")] = {
                "sekarang": val.get("last", {}).get("rating"),
                "tertinggi": val.get("best", {}).get("rating"),
                "rekor": val.get("record"),
            }
    if "tactics" in stats:
        ratings["puzzle_tertinggi"] = stats["tactics"].get("highest", {}).get("rating")

    return {
        "username": profile.get("username"),
        "nama": profile.get("name"),
        "negara": profile.get("country", "").rsplit("/", 1)[-1],
        "bergabung": datetime.fromtimestamp(profile.get("joined", 0), timezone.utc).date().isoformat(),
        "rating": ratings,
    }


@mcp.tool(description="Daftar game terbaru pemain (default 10). time_class opsional: rapid, blitz, bullet, daily.")
async def get_recent_games(username: str, count: int = 10, time_class: str | None = None) -> list[dict]:
    u = _clean(username)
    count = max(1, min(count, 50))
    archives = (await _get(f"{API}/player/{u}/games/archives")).get("archives", [])

    games: list[dict] = []
    for month_url in reversed(archives):
        month_games = (await _get(month_url)).get("games", [])
        for g in reversed(month_games):
            if time_class and g.get("time_class") != time_class:
                continue
            putih, hitam = g["white"], g["black"]
            sebagai = "putih" if putih["username"].lower() == u else "hitam"
            saya = putih if sebagai == "putih" else hitam
            lawan = hitam if sebagai == "putih" else putih
            games.append({
                "url": g.get("url"),
                "tanggal": datetime.fromtimestamp(g.get("end_time", 0), timezone.utc).date().isoformat(),
                "time_class": g.get("time_class"),
                "time_control": g.get("time_control"),
                "main_sebagai": sebagai,
                "hasil": saya.get("result"),
                "rating_saya": saya.get("rating"),
                "lawan": lawan.get("username"),
                "rating_lawan": lawan.get("rating"),
                "akurasi": g.get("accuracies"),
            })
            if len(games) >= count:
                return games
    return games


@mcp.tool(description="Ambil PGN lengkap satu game dari URL game Chess.com (hasil get_recent_games).")
async def get_game_pgn(username: str, game_url: str) -> str:
    u = _clean(username)
    archives = (await _get(f"{API}/player/{u}/games/archives")).get("archives", [])
    for month_url in reversed(archives):
        for g in (await _get(month_url)).get("games", []):
            if g.get("url") == game_url:
                return g.get("pgn", "PGN tidak tersedia.")
    return "Game tidak ditemukan di arsip pemain ini."


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        stateless_http=True,
    )
