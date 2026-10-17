import asyncio
import logging
from typing import Optional

from app.core.config import TIMING_CONFIG
from app.core.models import ServerModel
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PterodactylPowerGateway,
    RuntimeStateStoreProtocol,
)
from app.services.announcement_service import AnnouncementService

logger = logging.getLogger("updater.countdown_coordinator")


class CountdownCoordinatorService:
  """Responsible for countdown lifecycle management, multi-stage warning schedules, and triggering server restarts."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylPowerGateway,
      countdown: CountdownManagerProtocol,
      announcements: AnnouncementService,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
      restarted_builds: Optional[dict[str, str]] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.countdown = countdown
    self.announcements = announcements
    self.runtime_state = runtime_state
    self._restarted_builds: dict[str, str] = (
        restarted_builds if restarted_builds is not None else {}
    )

  def clear_restarted_build(self, server_id: Optional[str] = None) -> None:
    """Clears suppressed build tracking for a specific server or all servers."""
    if server_id:
      self._restarted_builds.pop(server_id, None)
    else:
      self._restarted_builds.clear()

  def has_restarted_build(self, server_id: str, latest_build: str) -> bool:
    """Checks if a restart was already dispatched for the specified build."""
    return self._restarted_builds.get(server_id) == latest_build

  def get_restarted_build(self, server_id: str) -> Optional[str]:
    return self._restarted_builds.get(server_id)

  def record_restarted_build(self, server_id: str, build_id: str) -> None:
    self._restarted_builds[server_id] = build_id

  def remove_restarted_build(self, server_id: str) -> None:
    self._restarted_builds.pop(server_id, None)

  def is_countdown_running(self, server_id: str) -> bool:
    return self.countdown.is_running(server_id)

  def stop_countdown(self, server_id: str) -> None:
    self.countdown.stop(server_id)

  def cancel_active_countdown(
      self, server: ServerModel, reason: str = ""
  ) -> None:
    """Aborts an in-progress countdown due to manual power signal or state divergence."""
    if self.countdown.is_running(server.server_id):
      logger.info(
          f"[{server.name}] Cancelling auto-restart countdown."
          + (f" Reason: {reason}" if reason else "")
      )
      self.countdown.stop(server.server_id)
      self._restarted_builds.pop(server.server_id, None)
      if reason:
        status_msg = (
            reason
            if "countdown cancelled" in reason.lower()
            else f"{reason} — countdown cancelled"
        )
      else:
        status_msg = "Countdown cancelled"
      object.__setattr__(server, "_ephemeral_last_status", status_msg)
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            last_status=status_msg,
        )

  async def broadcast_warning(
      self,
      server: ServerModel,
      minutes_left: int,
      include_patchnotes: bool = False,
  ) -> None:
    """Dispatches warning messages through the announcement service."""
    await self.announcements.broadcast_warning(
        server=server,
        minutes_left=minutes_left,
        include_patchnotes=include_patchnotes,
    )

  def start_countdown(self, server: ServerModel) -> asyncio.Task:
    """Schedules an asynchronous countdown restart routine and attaches it to the countdown manager."""
    task = asyncio.create_task(self.delayed_restart_routine(server))
    self.countdown.attach_task(server.server_id, task)
    return task

  async def delayed_restart_routine(self, server: ServerModel) -> None:
    """Executes the timed countdown sequence and issues the restart command via Pterodactyl API."""
    cfg = self.repo.load()
    total_seconds = TIMING_CONFIG.total_duration_seconds()
    self.countdown.start(server.server_id, total_seconds)
    warning_schedule = TIMING_CONFIG.compute_warning_schedule()
    first_min = warning_schedule[0][0] if warning_schedule else 15
    try:
      for mins, sleep_secs in warning_schedule:
        await self.broadcast_warning(
            server=server,
            minutes_left=mins,
            include_patchnotes=(mins == first_min),
        )
        await asyncio.sleep(sleep_secs)

      logger.info(
          f"[{server.name}] {total_seconds // 60}-minute countdown ended. Restarting server via Pterodactyl API."
      )
      status_msg = "Restarting server via Pterodactyl API..."
      object.__setattr__(server, "_ephemeral_last_status", status_msg)
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            last_status=status_msg,
        )
      st = (
          self.runtime_state.get_server_state(server.server_id)
          if self.runtime_state and server.server_id
          else None
      )
      latest_b = (
          st.latest_build
          if (st and st.latest_build != "Unknown")
          else getattr(server, "_ephemeral_latest_build", "Unknown")
      )
      self._restarted_builds[server.server_id] = latest_b
      self.countdown.stop(server.server_id)
      fresh_cfg = self.repo.load()
      panel_url = fresh_cfg.panel_url or cfg.panel_url
      api_key = fresh_cfg.api_key or cfg.api_key
      await self.ptero.trigger_restart(
          panel_url, api_key, server.server_id
      )
    except asyncio.CancelledError:
      logger.info(f"[{server.name}] Scheduled update countdown was cancelled.")
      raise
    finally:
      self.countdown.stop(server.server_id)
