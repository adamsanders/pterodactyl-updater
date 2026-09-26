import time
from typing import Dict, Optional


class PowerStateTracker:
  """Anti-corruption state filter that smooths over Pterodactyl Wings

  telemetry jitter, container recycling delays, and timeout fallbacks.
  """

  STARTUP_GRACE_DURATION: float = 30.0
  MAX_STARTUP_DURATION: float = 180.0
  STOPPING_GRACE_DURATION: float = 6.0
  RUNNING_CONFIRMATION_THRESHOLD: int = 2
  RESTART_LOCKOUT_DURATION: float = 8.0
  OFFLINE_CONFIRMATION_THRESHOLD: int = 3

  # Tiered Cache TTLs:
  # Transitional states require fast updates for UI snappiness
  TRANSITIONAL_CACHE_TTL: float = 2.5
  # Steady states cache longer to avoid spamming Wings (reduces steady-state CPM by ~80%)
  STEADY_CACHE_TTL: float = 15.0

  def __init__(self):
    self._states: Dict[str, dict] = {}

  def _get_ttl(self, state: str) -> float:
    if state in ("starting", "stopping"):
      return self.TRANSITIONAL_CACHE_TTL
    return self.STEADY_CACHE_TTL

  def _get_entry(self, server_id: str) -> dict:
    if server_id not in self._states:
      self._states[server_id] = {
          "smoothed_state": "unknown",
          "cached_state": "unknown",
          "cache_expires": 0.0,
          "starting_since": 0.0,
          "startup_grace_until": 0.0,
          "stopping_since": 0.0,
          "restart_lockout_until": 0.0,
          "consecutive_offline": 0,
          "consecutive_running": 0,
          "just_started": False,
      }
    return self._states[server_id]

  def invalidate(self, server_id: Optional[str] = None) -> None:
    """Flushes cached power state immediately for a server or all servers."""
    if server_id:
      entry = self._states.get(server_id)
      if entry:
        entry["cache_expires"] = 0.0
    else:
      for entry in self._states.values():
        entry["cache_expires"] = 0.0

  def register_signal(self, server_id: str, signal: str) -> str:
    now = time.time()
    entry = self._get_entry(server_id)

    if signal in ("start", "restart"):
      entry["smoothed_state"] = "starting"
      entry["cached_state"] = "starting"
      entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
      entry["starting_since"] = now
      entry["startup_grace_until"] = now + self.STARTUP_GRACE_DURATION
      entry["stopping_since"] = 0.0
      entry["consecutive_offline"] = 0
      entry["consecutive_running"] = 0
      entry["just_started"] = False
      if signal == "restart":
        entry["restart_lockout_until"] = now + self.RESTART_LOCKOUT_DURATION
      return "starting"

    if signal in ("stop", "kill"):
      entry["smoothed_state"] = "stopping"
      entry["cached_state"] = "stopping"
      entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
      entry["stopping_since"] = now
      entry["starting_since"] = 0.0
      entry["startup_grace_until"] = 0.0
      entry["restart_lockout_until"] = 0.0
      entry["consecutive_running"] = 0
      entry["just_started"] = False
      return "stopping"

    return entry["smoothed_state"]

  def get_valid_cache(self, server_id: str) -> Optional[str]:
    entry = self._get_entry(server_id)
    if entry["cache_expires"] > time.time():
      return entry["cached_state"]
    return None

  def filter_state(self, server_id: str, raw_state: str) -> str:
    now = time.time()
    entry = self._get_entry(server_id)
    prev = entry["smoothed_state"]
    normalized = (raw_state or "unknown").lower()

    if normalized == "unknown":
      entry["cached_state"] = prev if prev != "unknown" else "unknown"
      entry["cache_expires"] = now + self._get_ttl(entry["cached_state"])
      return entry["cached_state"]

    # Rule 1: Suppress stale "running" reports right after a restart signal
    if entry["restart_lockout_until"] > now:
      if normalized == "running":
        entry["cached_state"] = "starting"
        entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
        return "starting"
      elif normalized in ("stopping", "offline", "starting"):
        entry["restart_lockout_until"] = 0.0

    # Rule 2: Handle telemetry while server is in "stopping"
    if prev == "stopping":
      stopping_duration = now - entry["stopping_since"]

      # Clean transition to offline once container exits
      if normalized in ("offline", "stopped"):
        entry["smoothed_state"] = "offline"
        entry["cached_state"] = "offline"
        entry["cache_expires"] = now + self.STEADY_CACHE_TTL
        entry["stopping_since"] = 0.0
        entry["consecutive_running"] = 0
        return "offline"

      if normalized in ("running", "starting"):
        entry["consecutive_running"] += 1
        in_grace = stopping_duration < self.STOPPING_GRACE_DURATION

        # Suppress brief 1-poll residual running while container halts
        if (
            in_grace
            and entry["consecutive_running"]
            < self.RUNNING_CONFIRMATION_THRESHOLD
        ):
          entry["cached_state"] = "stopping"
          entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
          return "stopping"

        # Stop command was dropped/ignored during boot; accept that the server is alive
        if normalized == "running":
          entry["just_started"] = True
        entry["smoothed_state"] = normalized
        entry["cached_state"] = normalized
        entry["cache_expires"] = now + self._get_ttl(normalized)
        entry["stopping_since"] = 0.0
        entry["consecutive_running"] = 0
        return normalized

    # Rule 3: Suppress spurious "offline" reports while in "starting"
    if prev == "starting":
      if normalized == "offline":
        entry["consecutive_offline"] += 1
        in_grace_period = now < entry["startup_grace_until"]
        startup_expired = (
            now - entry["starting_since"]
        ) > self.MAX_STARTUP_DURATION

        if (
            in_grace_period
            or entry["consecutive_offline"]
            < self.OFFLINE_CONFIRMATION_THRESHOLD
        ) and not startup_expired:
          entry["cached_state"] = "starting"
          entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
          return "starting"
      elif normalized in ("running", "starting"):
        entry["consecutive_offline"] = 0

    if normalized == "starting" and prev != "starting":
      entry["starting_since"] = now
      entry["startup_grace_until"] = now + self.STARTUP_GRACE_DURATION
      entry["consecutive_offline"] = 0

    # Rule 4: Instant transition to Online when Wings reports running
    if normalized == "running":
      if prev == "starting":
        entry["just_started"] = True
      entry["starting_since"] = 0.0
      entry["startup_grace_until"] = 0.0
      entry["consecutive_offline"] = 0

    entry["smoothed_state"] = normalized
    entry["cached_state"] = normalized
    entry["cache_expires"] = now + self._get_ttl(normalized)
    return normalized

  def pop_just_started(self, server_id: str) -> bool:
    entry = self._get_entry(server_id)
    if entry.get("just_started", False):
      entry["just_started"] = False
      return True
    return False