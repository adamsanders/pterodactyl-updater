import asyncio
import time
from typing import Dict, Optional


class CountdownManager:
  """Manages countdown expiration timestamps and binds to cancellable asyncio tasks."""

  def __init__(self):
    self._targets: Dict[str, float] = {}
    self._tasks: Dict[str, asyncio.Task] = {}

  def start(
      self,
      server_id: str,
      duration_seconds: int = 900,
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
    if task and not task.done():
      task.cancel()

  def get_target(self, server_id: str) -> float:
    return self._targets.get(server_id, 0.0)

  def is_running(self, server_id: str) -> bool:
    return server_id in self._targets and self._targets[server_id] > time.time()

  def get_remaining(self, server_id: str) -> int:
    target = self.get_target(server_id)
    rem = int(target - time.time())
    return max(rem, 0)