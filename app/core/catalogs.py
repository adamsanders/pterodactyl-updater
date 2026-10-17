"""Domain reference catalogs and translation utilities for Steam games and dedicated servers."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
import warnings


@dataclass(frozen=True)
class GameCatalogEntry(Mapping[str, Any]):
    """Typed domain reference catalog entry for popular dedicated game servers."""

    app_id: str
    name: str
    manifest_name: str = ""
    default_query_offset: int = 0
    game: str = ""

    _FIELDS = ("app_id", "name", "manifest_name", "default_query_offset", "game")

    def __post_init__(self) -> None:
        if not self.manifest_name:
            object.__setattr__(self, "manifest_name", f"appmanifest_{self.app_id}.acf")
        if not self.game:
            object.__setattr__(self, "game", self.name)

    def __getitem__(self, key: str) -> Any:
        if key in self._FIELDS:
            return getattr(self, key)
        raise KeyError(key)

    def __len__(self) -> int:
        return len(self._FIELDS)

    def __iter__(self):
        return iter(self._FIELDS)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self._FIELDS}


# Steam redistributable / auxiliary tool App IDs that must never be treated as game servers
IGNORED_STEAM_APPIDS: set[str] = {
    "1007",    # Steamworks SDK Redist
    "228980",  # Steamworks Common Redistributables
    "1008",    # Steamworks SDK Dedicated Server
    "1009",    # Steamworks SDK Win32
    "0",
}

SERVER_TO_GAME_APPID: dict[str, str] = {
    "896660": "892970",    # Valheim Dedicated Server -> Valheim
    "2394010": "1623730",  # Palworld Dedicated Server -> Palworld
    "2278520": "1203620",  # Enshrouded Dedicated Server -> Enshrouded
    "258550": "252490",    # Rust Dedicated Server -> Rust
    "376030": "346110",    # ARK: Survival Evolved -> ARK
    "2430930": "2399830",  # ARK: Survival Ascended -> ASA
    "2465200": "1326470",  # Sons of the Forest Dedicated Server -> SotF
    "1829350": "1604030",  # V Rising Dedicated Server -> V Rising
    "294420": "251570",    # 7 Days to Die Dedicated Server -> 7 Days to Die
    "380870": "108600",    # Project Zomboid Dedicated Server -> PZ
    "443030": "440900",    # Conan Exiles Dedicated Server -> Conan Exiles
    "1690800": "526870",   # Satisfactory Dedicated Server -> Satisfactory
}

GAME_TO_SERVER_APPID: dict[str, str] = {
    v: k for k, v in SERVER_TO_GAME_APPID.items()
}

POPULAR_DEDICATED_SERVERS: list[GameCatalogEntry] = [
    GameCatalogEntry(app_id="896660", name="Valheim Dedicated Server", game="Valheim", default_query_offset=1),
    GameCatalogEntry(app_id="2278520", name="Enshrouded Dedicated Server", game="Enshrouded", default_query_offset=1),
    GameCatalogEntry(app_id="2394010", name="Palworld Dedicated Server", game="Palworld"),
    GameCatalogEntry(app_id="258550", name="Rust Dedicated Server", game="Rust"),
    GameCatalogEntry(app_id="1829350", name="V Rising Dedicated Server", game="V Rising", default_query_offset=1),
    GameCatalogEntry(app_id="294420", name="7 Days to Die Dedicated Server", game="7 Days to Die", default_query_offset=1),
    GameCatalogEntry(app_id="1690800", name="Satisfactory Dedicated Server", game="Satisfactory"),
    GameCatalogEntry(app_id="380870", name="Project Zomboid Dedicated Server", game="Project Zomboid"),
    GameCatalogEntry(app_id="443030", name="Conan Exiles Dedicated Server", game="Conan Exiles"),
    GameCatalogEntry(app_id="2465200", name="Sons of the Forest Dedicated Server", game="Sons of the Forest"),
    GameCatalogEntry(app_id="376030", name="ARK: Survival Evolved Dedicated Server", game="ARK: Survival Evolved"),
    GameCatalogEntry(app_id="2430930", name="ARK: Survival Ascended Dedicated Server", game="ARK: Survival Ascended"),
    GameCatalogEntry(app_id="4020", name="Garry's Mod Dedicated Server", game="Garry's Mod"),
    GameCatalogEntry(app_id="740", name="Counter-Strike: Global Offensive Dedicated Server", game="CS:GO"),
    GameCatalogEntry(app_id="232250", name="Team Fortress 2 Dedicated Server", game="Team Fortress 2"),
    GameCatalogEntry(app_id="107410", name="Arma 3 Server", game="Arma 3"),
    GameCatalogEntry(app_id="233780", name="Arma Reforger Server", game="Arma Reforger"),
    GameCatalogEntry(app_id="223350", name="Left 4 Dead 2 Dedicated Server", game="Left 4 Dead 2"),
    GameCatalogEntry(app_id="1110390", name="DayZ Server", game="DayZ"),
    GameCatalogEntry(app_id="393390", name="Squad Dedicated Server", game="Squad"),
    GameCatalogEntry(app_id="283200", name="Unturned Dedicated Server", game="Unturned"),
    GameCatalogEntry(app_id="996560", name="Barotrauma Dedicated Server", game="Barotrauma"),
    GameCatalogEntry(app_id="696370", name="Astroneer Dedicated Server", game="Astroneer"),
    GameCatalogEntry(app_id="1963720", name="Icarus Dedicated Server", game="Icarus"),
    GameCatalogEntry(app_id="581330", name="Terraria Dedicated Server", game="Terraria"),
]


def resolve_game_appid(appid: int | str) -> str:
    """Resolves a dedicated server app ID to its base game app ID if mapped."""
    if appid is None:
        return ""
    s_id = str(appid).strip()
    return SERVER_TO_GAME_APPID.get(s_id, s_id)


# Games where the Steam A2S query port is typically offset from the game allocation port
# Deprecation Warning: Hardcoded PORT_OFFSET_MAP is deprecated as of v1.14.0 and scheduled for removal in v2.0.0.
# Query port offsets should now be configured per-server via ServerModel.query_port_offset.
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
"""Deprecation Warning: PORT_OFFSET_MAP is deprecated as of v1.14.0 and scheduled for removal in v2.0.0.
Query port offsets should now be configured per-server via ServerModel.query_port_offset.
"""


def resolve_query_port(
    app_id: int | str, game_port: int | str, query_port_offset: int | str = 0
) -> int:
    """Translates a game's connection/allocation port to its Steam A2S query port.

    If query_port_offset is non-zero, it is applied directly to game_port.
    If query_port_offset is 0, it falls back to PORT_OFFSET_MAP for backward compatibility.
    Note: Fallback to PORT_OFFSET_MAP is deprecated since v1.14.0 and will be removed in v2.0.0.
    """
    try:
        gport = int(str(game_port).strip())
    except (ValueError, TypeError):
        return 0

    if gport <= 0:
        return 0

    try:
        offset_val = int(str(query_port_offset).strip())
    except (ValueError, TypeError):
        offset_val = 0

    if offset_val != 0:
        resolved = gport + offset_val
        return resolved if 0 < resolved <= 65535 else 0

    try:
        aid = int(str(app_id).strip())
    except (ValueError, TypeError):
        return gport

    if aid in PORT_OFFSET_MAP:
        warnings.warn(
            "PORT_OFFSET_MAP fallback is deprecated and will be removed in v2.0.0. Configure query_port_offset on the server.",
            DeprecationWarning,
            stacklevel=2,
        )

    offset = PORT_OFFSET_MAP.get(aid, 0)
    resolved = gport + offset
    return resolved if 0 < resolved <= 65535 else 0


__all__ = [
    "GameCatalogEntry",
    "IGNORED_STEAM_APPIDS",
    "SERVER_TO_GAME_APPID",
    "GAME_TO_SERVER_APPID",
    "POPULAR_DEDICATED_SERVERS",
    "PORT_OFFSET_MAP",
    "resolve_game_appid",
    "resolve_query_port",
]
