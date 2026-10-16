from dataclasses import dataclass
import functools
import os
from typing import Any, List, Tuple

from app.core.catalogs import (
    GameCatalogEntry,
    IGNORED_STEAM_APPIDS,
    SERVER_TO_GAME_APPID,
    GAME_TO_SERVER_APPID,
    POPULAR_DEDICATED_SERVERS,
    PORT_OFFSET_MAP,
    resolve_game_appid,
    resolve_query_port,
)

CONFIG_PATH = os.getenv(
    "CONFIG_PATH",
    "/data/config.json" if os.path.exists("/data/config.json") else "config.json",
)

APP_VERSION = os.getenv("APP_VERSION", "1.21.0")
DEFAULT_COMMIT_CODE = "92206dc"


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
    """Resolves the current Git commit short hash from env, git repository, or metadata files."""
    for env_var in ("GIT_COMMIT", "COMMIT_SHA", "APP_COMMIT", "GIT_SHA", "COMMIT_CODE"):
        val = os.getenv(env_var, "").strip()
        if val and val.lower() != "unknown":
            val = val.replace("commit", "").strip()
            if len(val) >= 7:
                return val[:7]

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    core_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Try git rev-parse if git CLI and repository are present
    try:
        import subprocess

        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=1,
            text=True,
        ).strip()
        if output and output.lower() != "unknown":
            return output[:7]
    except Exception:
        pass

    # 2. Try native parsing of .git directory or worktree gitdir file
    try:
        git_entry = os.path.join(repo_root, ".git")
        git_dir = git_entry
        if os.path.isfile(git_entry):
            with open(git_entry, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("gitdir:"):
                raw_gitdir = content[7:].strip()
                git_dir = os.path.abspath(os.path.join(repo_root, raw_gitdir))

        head_path = os.path.join(git_dir, "HEAD")
        if os.path.isfile(head_path):
            with open(head_path, "r", encoding="utf-8") as f:
                ref = f.read().strip()
            if ref.startswith("ref: "):
                ref_rel = ref[5:].strip()
                ref_file = os.path.join(git_dir, *ref_rel.split("/"))
                if os.path.isfile(ref_file):
                    with open(ref_file, "r", encoding="utf-8") as f:
                        sha = f.read().strip()
                        if sha:
                            return sha[:7]
                packed_path = os.path.join(git_dir, "packed-refs")
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

    # 3. Check commit metadata files (e.g. copied into Docker image or created during release)
    candidate_files = [
        os.path.join(app_dir, "commit.txt"),
        os.path.join(core_dir, "commit.txt"),
        os.path.join(repo_root, ".commit"),
        os.path.join(repo_root, "commit.txt"),
        os.path.join(repo_root, "COMMIT_HASH"),
    ]
    for cfile in candidate_files:
        try:
            if os.path.isfile(cfile):
                with open(cfile, "r", encoding="utf-8") as f:
                    cval = f.read().strip()
                if cval and cval.lower() != "unknown":
                    cval = cval.replace("commit", "").strip()
                    if len(cval) >= 7:
                        return cval[:7]
        except Exception:
            pass

    return DEFAULT_COMMIT_CODE


@functools.lru_cache(maxsize=1)
def get_commit_code() -> str:
    """Returns the resolved git commit short hash, lazily cached across calls."""
    return resolve_commit_code()


def __getattr__(name: str) -> Any:
    if name == "COMMIT_CODE":
        return get_commit_code()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + ["COMMIT_CODE"])


__all__ = [
    "CONFIG_PATH",
    "APP_VERSION",
    "DEFAULT_COMMIT_CODE",
    "COMMIT_CODE",
    "get_commit_code",
    "resolve_commit_code",
    "TimingConfig",
    "TIMING_CONFIG",
    "GameCatalogEntry",
    "IGNORED_STEAM_APPIDS",
    "SERVER_TO_GAME_APPID",
    "GAME_TO_SERVER_APPID",
    "POPULAR_DEDICATED_SERVERS",
    "PORT_OFFSET_MAP",
    "resolve_game_appid",
    "resolve_query_port",
]
