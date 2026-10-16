from dataclasses import dataclass
import os
from typing import List, Tuple

CONFIG_PATH = os.getenv(
    "CONFIG_PATH",
    "/data/config.json" if os.path.exists("/data/config.json") else "config.json",
)

APP_VERSION = os.getenv("APP_VERSION", "1.17.1")

# Steam redistributable / auxiliary tool App IDs that must never be treated as game servers
IGNORED_STEAM_APPIDS: set[str] = {
    "1007",    # Steamworks SDK Redist
    "228980",  # Steamworks Common Redistributables
    "1008",    # Steamworks SDK Dedicated Server
    "1009",    # Steamworks SDK Win32
    "0",
}



@dataclass(frozen=True)
class TimingConfig:
    """Centralized domain constants for timeouts, cache TTLs, and countdown routines."""

    # HTTP and Network Timeouts (seconds)
    http_timeout: float = 10.0
    a2s_timeout: float = 1.5
    a2s_cache_ttl: float = 30.0

    # Power Tracker Cache TTLs (seconds)
    power_transitional_ttl: float = 1.0
    power_steady_ttl: float = 15.0

    # Power State Filter Durations (seconds)
    startup_grace_duration: float = 30.0
    max_startup_duration: float = 180.0
    max_stopping_duration: float = 45.0
    aborted_start_stop_grace: float = 8.0
    restart_lockout_duration: float = 8.0

    # Client Polling Intervals (milliseconds)
    client_steady_poll_ms: int = 4000
    client_fast_poll_ms: int = 1500
    client_background_poll_ms: int = 8000

    # Default Countdown & Warning Schedule (minutes)
    default_countdown_stages: Tuple[int, ...] = (15, 10, 5, 1)

    @classmethod
    def compute_warning_schedule(
        cls, stages: Tuple[int, ...] = (15, 10, 5, 1)
    ) -> List[Tuple[int, int]]:
        """Calculates (minutes_remaining, sleep_seconds) pairs from descending stage list.

        Example for (15, 10, 5, 1):
          - 15m left -> sleep (15-10)*60 = 300s
          - 10m left -> sleep (10-5)*60  = 300s
          -  5m left -> sleep (5-1)*60   = 240s
          -  1m left -> sleep (1-0)*60   = 60s
          Total sleep = 900s (15 minutes).
        """
        if not stages:
            return []
        sorted_stages = sorted(stages, reverse=True)
        schedule = []
        for i, current_min in enumerate(sorted_stages):
            next_min = sorted_stages[i + 1] if i + 1 < len(sorted_stages) else 0
            sleep_secs = (current_min - next_min) * 60
            schedule.append((current_min, sleep_secs))
        return schedule

    @classmethod
    def total_duration_seconds(cls, stages: Tuple[int, ...] = (15, 10, 5, 1)) -> int:
        """Returns total countdown duration in seconds from the earliest warning stage."""
        if not stages:
            return 0
        return max(stages) * 60


TIMING_CONFIG = TimingConfig()



def resolve_commit_code() -> str:
    """Resolves the current Git commit short hash from env or git repository."""
    for env_var in ("GIT_COMMIT", "COMMIT_SHA", "APP_COMMIT", "GIT_SHA"):
        val = os.getenv(env_var, "").strip()
        if val:
            return val[:7]

    try:
        import subprocess

        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=1,
            text=True,
        ).strip()
        if output:
            return output[:7]
    except Exception:
        pass

    try:
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        head_path = os.path.join(repo_root, ".git", "HEAD")
        if os.path.isfile(head_path):
            with open(head_path, "r", encoding="utf-8") as f:
                ref = f.read().strip()
            if ref.startswith("ref: "):
                ref_rel = ref[5:].strip()
                ref_file = os.path.join(repo_root, ".git", *ref_rel.split("/"))
                if os.path.isfile(ref_file):
                    with open(ref_file, "r", encoding="utf-8") as f:
                        sha = f.read().strip()
                        if sha:
                            return sha[:7]
                packed_path = os.path.join(repo_root, ".git", "packed-refs")
                if os.path.isfile(packed_path):
                    with open(packed_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str and not line_str.startswith(("#", "^")):
                                parts = line_str.split()
                                if len(parts) == 2 and parts[1] == ref_rel:
                                    return parts[0][:7]
            elif len(ref) >= 7:
                return ref[:7]
    except Exception:
        pass

    return "unknown"


COMMIT_CODE = resolve_commit_code()

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

GAME_TO_SERVER_APPID: dict[str, str] = {
    v: k for k, v in SERVER_TO_GAME_APPID.items()
}

POPULAR_DEDICATED_SERVERS: list[dict] = [
    {"app_id": "896660", "name": "Valheim Dedicated Server", "game": "Valheim"},
    {"app_id": "2278520", "name": "Enshrouded Dedicated Server", "game": "Enshrouded"},
    {"app_id": "2394010", "name": "Palworld Dedicated Server", "game": "Palworld"},
    {"app_id": "258550", "name": "Rust Dedicated Server", "game": "Rust"},
    {"app_id": "1829350", "name": "V Rising Dedicated Server", "game": "V Rising"},
    {"app_id": "294420", "name": "7 Days to Die Dedicated Server", "game": "7 Days to Die"},
    {"app_id": "1690800", "name": "Satisfactory Dedicated Server", "game": "Satisfactory"},
    {"app_id": "380870", "name": "Project Zomboid Dedicated Server", "game": "Project Zomboid"},
    {"app_id": "443030", "name": "Conan Exiles Dedicated Server", "game": "Conan Exiles"},
    {"app_id": "2465200", "name": "Sons of the Forest Dedicated Server", "game": "Sons of the Forest"},
    {"app_id": "376030", "name": "ARK: Survival Evolved Dedicated Server", "game": "ARK: Survival Evolved"},
    {"app_id": "2430930", "name": "ARK: Survival Ascended Dedicated Server", "game": "ARK: Survival Ascended"},
    {"app_id": "4020", "name": "Garry's Mod Dedicated Server", "game": "Garry's Mod"},
    {"app_id": "740", "name": "Counter-Strike: Global Offensive Dedicated Server", "game": "CS:GO"},
    {"app_id": "232250", "name": "Team Fortress 2 Dedicated Server", "game": "Team Fortress 2"},
    {"app_id": "107410", "name": "Arma 3 Server", "game": "Arma 3"},
    {"app_id": "233780", "name": "Arma Reforger Server", "game": "Arma Reforger"},
    {"app_id": "223350", "name": "Left 4 Dead 2 Dedicated Server", "game": "Left 4 Dead 2"},
    {"app_id": "1110390", "name": "DayZ Server", "game": "DayZ"},
    {"app_id": "393390", "name": "Squad Dedicated Server", "game": "Squad"},
    {"app_id": "283200", "name": "Unturned Dedicated Server", "game": "Unturned"},
    {"app_id": "996560", "name": "Barotrauma Dedicated Server", "game": "Barotrauma"},
    {"app_id": "696370", "name": "Astroneer Dedicated Server", "game": "Astroneer"},
    {"app_id": "1963720", "name": "Icarus Dedicated Server", "game": "Icarus"},
    {"app_id": "581330", "name": "Terraria Dedicated Server", "game": "Terraria"},
]


def resolve_game_appid(appid: int | str) -> str:
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

    offset = PORT_OFFSET_MAP.get(aid, 0)
    resolved = gport + offset
    return resolved if 0 < resolved <= 65535 else 0
