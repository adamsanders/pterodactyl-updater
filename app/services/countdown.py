import asyncio
import time
from typing import Dict, Optional
from app.core.config import TIMING_CONFIG


class CountdownManager:
  """Manages countdown expiration timestamps and binds to cancellable asyncio tasks."""

  def __init__(self):
    self._targets: Dict[str, float] = {}
    self._tasks: Dict[str, asyncio.Task] = {}

  def start(
      self,
      server_id: str,
      duration_seconds: int = TIMING_CONFIG.total_duration_seconds(),
      task: Optional[asyncio.Task] = None,
  ) -> None:
    self._targets[server_id] = time.time() + duration_seconds
    if task:
      self.attach_task(server_id, task)

  def attach_task(self, server_id: str, task: asyncio.Task) -> None:
    existing = self._tasks.get(server_id)
    if existing and not existing.done() and existing is not task:
      existing.cancel()
    self._tasks[server_id] = task

  def stop(self, server_id: str) -> None:
    self._targets.pop(server_id, None)
    task = self._tasks.pop(server_id, None)
    current = None
    try:
      current = asyncio.current_task()
    except RuntimeError:
      pass
    if task and not task.done() and task is not current:
      task.cancel()

  def stop_all(self) -> list[asyncio.Task]:
    """Cancels all active countdown tasks and clears expiration targets."""
    tasks: list[asyncio.Task] = []
    all_server_ids = set(self._tasks.keys()) | set(self._targets.keys())
    for server_id in all_server_ids:
      task = self._tasks.get(server_id)
      if task and not task.done():
        tasks.append(task)
      self.stop(server_id)
    self._targets.clear()
    return tasks

  def active_server_ids(self) -> list[str]:
    """Returns list of server IDs currently running a countdown task or unexpired target."""
    now = time.time()
    active = set()
    for sid, task in self._tasks.items():
      if not task.done():
        active.add(sid)
    for sid, target in self._targets.items():
      if target > now:
        active.add(sid)
    return list(active)

  def get_target(self, server_id: str) -> float:
    return self._targets.get(server_id, 0.0)

  def is_running(self, server_id: str) -> bool:
    task = self._tasks.get(server_id)
    if task and not task.done():
      return True
    return server_id in self._targets and self._targets[server_id] > time.time()

  def get_remaining(self, server_id: str) -> int:
    target = self.get_target(server_id)
    rem = int(target - time.time())
    return max(rem, 0)