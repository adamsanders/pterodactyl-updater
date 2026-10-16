import time
from typing import Dict, Optional, Union
from app.core.config import TIMING_CONFIG
from app.core.models import PowerSignal, PowerState


class PowerStateTracker:
  """Anti-corruption state filter that smooths over Pterodactyl Wings

  telemetry jitter, container recycling delays, and timeout fallbacks.
  """

  STARTUP_GRACE_DURATION: float = TIMING_CONFIG.startup_grace_duration
  MAX_STARTUP_DURATION: float = TIMING_CONFIG.max_startup_duration
  MAX_STOPPING_DURATION: float = TIMING_CONFIG.max_stopping_duration
  # Grace period if Stop was clicked while the container was in "starting"
  ABORTED_START_STOP_GRACE: float = TIMING_CONFIG.aborted_start_stop_grace
  RESTART_LOCKOUT_DURATION: float = TIMING_CONFIG.restart_lockout_duration
  OFFLINE_CONFIRMATION_THRESHOLD: int = 3

  # Tiered Cache TTLs:
  # Transitional states require fast updates (1.0) for UI responsiveness
  TRANSITIONAL_CACHE_TTL: float = TIMING_CONFIG.power_transitional_ttl
  # Steady states cache longer (15s) to avoid spamming Wings
  STEADY_CACHE_TTL: float = TIMING_CONFIG.power_steady_ttl

  def __init__(self):
    self._states: Dict[str, dict] = {}

  def _get_ttl(self, state: Union[PowerState, str]) -> float:
    p_state = PowerState.from_str(state)
    if p_state in (PowerState.STARTING, PowerState.STOPPING):
      return self.TRANSITIONAL_CACHE_TTL
    return self.STEADY_CACHE_TTL

  def _get_entry(self, server_id: str) -> dict:
    if server_id not in self._states:
      self._states[server_id] = {
          "smoothed_state": PowerState.UNKNOWN,
          "cached_state": PowerState.UNKNOWN,
          "cache_expires": 0.0,
          "starting_since": 0.0,
          "startup_grace_until": 0.0,
          "stopping_since": 0.0,
          "stopped_during_start": False,
          "restart_lockout_until": 0.0,
          "consecutive_offline": 0,
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

  def register_signal(
      self, server_id: str, signal: Union[PowerSignal, str]
  ) -> PowerState:
    now = time.time()
    entry = self._get_entry(server_id)
    prev = PowerState.from_str(entry["smoothed_state"])

    try:
      sig = PowerSignal.from_str(signal)
    except (ValueError, TypeError):
      sig = None

    if sig in (PowerSignal.START, PowerSignal.RESTART):
      entry["smoothed_state"] = PowerState.STARTING
      entry["cached_state"] = PowerState.STARTING
      entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
      entry["starting_since"] = now
      entry["startup_grace_until"] = now + self.STARTUP_GRACE_DURATION
      entry["stopping_since"] = 0.0
      entry["stopped_during_start"] = False
      entry["consecutive_offline"] = 0
      entry["just_started"] = False
      if sig == PowerSignal.RESTART:
        entry["restart_lockout_until"] = now + self.RESTART_LOCKOUT_DURATION
      return PowerState.STARTING

    if sig in (PowerSignal.STOP, PowerSignal.KILL):
      entry["smoothed_state"] = PowerState.STOPPING
      entry["cached_state"] = PowerState.STOPPING
      entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
      entry["stopping_since"] = now
      entry["stopped_during_start"] = (prev == PowerState.STARTING)
      entry["starting_since"] = 0.0
      entry["startup_grace_until"] = 0.0
      entry["restart_lockout_until"] = 0.0
      entry["just_started"] = False
      return PowerState.STOPPING

    return entry["smoothed_state"]

  def get_valid_cache(self, server_id: str) -> Optional[PowerState]:
    entry = self._get_entry(server_id)
    if entry["cache_expires"] > time.time():
      return entry["cached_state"]
    return None

  def filter_state(
      self, server_id: str, raw_state: Optional[Union[PowerState, str]]
  ) -> PowerState:
    now = time.time()
    entry = self._get_entry(server_id)
    prev = PowerState.from_str(entry["smoothed_state"])
    normalized = PowerState.from_str(raw_state)

    if normalized == PowerState.UNKNOWN:
      entry["cached_state"] = (
          prev if prev != PowerState.UNKNOWN else PowerState.UNKNOWN
      )
      entry["cache_expires"] = now + self._get_ttl(entry["cached_state"])
      return entry["cached_state"]

    # Rule 1: Suppress stale "running" reports right after a restart signal
    if entry["restart_lockout_until"] > now:
      if normalized == PowerState.RUNNING:
        entry["cached_state"] = PowerState.STARTING
        entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
        return PowerState.STARTING
      elif normalized in (
          PowerState.STOPPING,
          PowerState.OFFLINE,
          PowerState.STARTING,
      ):
        entry["restart_lockout_until"] = 0.0

    # Rule 2: Handle telemetry while server is in "stopping"
    if prev == PowerState.STOPPING:
      stopping_duration = now - entry["stopping_since"]

      # Clean transition to offline once container exits
      if normalized == PowerState.OFFLINE:
        entry["smoothed_state"] = PowerState.OFFLINE
        entry["cached_state"] = PowerState.OFFLINE
        entry["cache_expires"] = now + self.STEADY_CACHE_TTL
        entry["stopping_since"] = 0.0
        entry["stopped_during_start"] = False
        return PowerState.OFFLINE

      if normalized == PowerState.RUNNING:
        # Special edge case: user clicked Stop while container was booting, and boot script ignored it
        if (
            entry["stopped_during_start"]
            and stopping_duration > self.ABORTED_START_STOP_GRACE
        ):
          entry["smoothed_state"] = PowerState.RUNNING
          entry["cached_state"] = PowerState.RUNNING
          entry["cache_expires"] = now + self.STEADY_CACHE_TTL
          entry["stopping_since"] = 0.0
          entry["stopped_during_start"] = False
          return PowerState.RUNNING

        # Normal shutdown: container is still flushing world saves
        if stopping_duration < self.MAX_STOPPING_DURATION:
          entry["cached_state"] = PowerState.STOPPING
          entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
          return PowerState.STOPPING

        # Timed out waiting for stop (exceeded 45s)
        entry["smoothed_state"] = PowerState.RUNNING
        entry["cached_state"] = PowerState.RUNNING
        entry["cache_expires"] = now + self.STEADY_CACHE_TTL
        entry["stopping_since"] = 0.0
        return PowerState.RUNNING

      if normalized == PowerState.STOPPING:
        entry["cached_state"] = PowerState.STOPPING
        entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
        return PowerState.STOPPING

    # Rule 3: Suppress spurious "offline" reports while in "starting"
    if prev == PowerState.STARTING:
      if normalized == PowerState.OFFLINE:
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
          entry["cached_state"] = PowerState.STARTING
          entry["cache_expires"] = now + self.TRANSITIONAL_CACHE_TTL
          return PowerState.STARTING
      elif normalized in (PowerState.RUNNING, PowerState.STARTING):
        entry["consecutive_offline"] = 0

    if (
        normalized == PowerState.STARTING
        and prev != PowerState.STARTING
    ):
      entry["starting_since"] = now
      entry["startup_grace_until"] = now + self.STARTUP_GRACE_DURATION
      entry["consecutive_offline"] = 0

    # Rule 4: Instant transition to Online when Wings reports running
    if normalized == PowerState.RUNNING:
      if prev == PowerState.STARTING:
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