import os

CONFIG_PATH = os.getenv(
    "CONFIG_PATH",
    "/data/config.json" if os.path.exists("/data/config.json") else "config.json",
)

SERVER_TO_GAME_APPID: dict[str, str] = {
    "896660": "892970",  # Valheim Dedicated Server -> Valheim
    "2394010": "1623730",  # Palworld Dedicated Server -> Palworld
    "2278520": "1203620",  # Enshrouded Dedicated Server -> Enshrouded
    "258550": "252490",  # Rust Dedicated Server -> Rust
    "376030": "346110",  # ARK: Survival Evolved -> ARK
    "2430930": "2399830",  # ARK: Survival Ascended -> ASA
    "2465200": "1326470",  # Sons of the Forest Dedicated Server -> SotF
    "1829350": "1604030",  # V Rising Dedicated Server -> V Rising
    "294420": "251570",  # 7 Days to Die Dedicated Server -> 7 Days to Die
    "380870": "108600",  # Project Zomboid Dedicated Server -> PZ
    "443030": "440900",  # Conan Exiles Dedicated Server -> Conan Exiles
    "1690800": "526870",  # Satisfactory Dedicated Server -> Satisfactory
}


def resolve_game_appid(appid: int | str) -> str:
  s_id = str(appid).strip()
  return SERVER_TO_GAME_APPID.get(s_id, s_id)

# Games where the Steam A2S query port is typically offset from the game allocation port
PORT_OFFSET_MAP: dict[int, int] = {
    896660: 1,   # Valheim (Game + 1)
    892970: 1,   # Valheim Dedicated
    2278520: 1,  # Enshrouded (Game + 1)
    1203620: 1,  # Enshrouded Dedicated
    1829350: 1,  # V Rising (Game + 1)
    1604030: 1,  # V Rising Dedicated
    294420: 1,   # 7 Days to Die (Game + 1)
    251570: 1,   # 7 Days to Die Dedicated
}

def resolve_query_port(app_id: int | str, game_port: int) -> int:
    """Translates a game's connection/allocation port to its Steam A2S query port."""
    if not game_port:
        return 0
    try:
        aid = int(str(app_id).strip())
    except (ValueError, TypeError):
        return game_port

    offset = PORT_OFFSET_MAP.get(aid, 0)
    return game_port + offset