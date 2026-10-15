import threading
from typing import Dict, Optional
from app.core.models import AppConfigModel, AppRuntimeState, ServerRuntimeState


class RuntimeStateStore:
  """Thread-safe in-memory store for transient telemetry and runtime statuses.

  Decouples ephemeral game server build IDs and operational status messages from
  the persistent user configuration on disk.
  """

  def __init__(self):
    self._lock = threading.RLock()
    self._global_state = AppRuntimeState()
    self._server_states: Dict[str, ServerRuntimeState] = {}

  def get_global_state(self) -> AppRuntimeState:
    with self._lock:
      return self._global_state.model_copy()

  def update_global_state(
      self,
      last_check: Optional[str] = None,
      last_status: Optional[str] = None,
  ) -> AppRuntimeState:
    with self._lock:
      updates = {}
      if last_check is not None:
        updates["last_check"] = last_check
      if last_status is not None:
        updates["last_status"] = last_status
      updated = self._global_state.model_copy(update=updates)
      self._global_state = updated
      return updated

  def get_server_state(self, server_id: str) -> ServerRuntimeState:
    s_id = str(server_id).strip()
    with self._lock:
      if s_id not in self._server_states:
        self._server_states[s_id] = ServerRuntimeState(server_id=s_id)
      return self._server_states[s_id].model_copy()

  def update_server_state(
      self,
      server_id: str,
      current_build: Optional[str] = None,
      latest_build: Optional[str] = None,
      last_status: Optional[str] = None,
  ) -> ServerRuntimeState:
    s_id = str(server_id).strip()
    with self._lock:
      current = self.get_server_state(s_id)
      updates = {}
      if current_build is not None:
        updates["current_build"] = current_build
      if latest_build is not None:
        updates["latest_build"] = latest_build
      if last_status is not None:
        updates["last_status"] = last_status

      updated = current.model_copy(update=updates)
      self._server_states[s_id] = updated
      return updated

  def get_all_server_states(self) -> Dict[str, ServerRuntimeState]:
    with self._lock:
      return {k: v.model_copy() for k, v in self._server_states.items()}

  def seed_from_config(self, config: AppConfigModel) -> None:
    with self._lock:
      if config.last_check != "Never":
        self._global_state.last_check = config.last_check
      if config.last_status != "Idle":
        self._global_state.last_status = config.last_status

      for srv in config.servers:
        s_id = str(srv.server_id).strip()
        if not s_id:
          continue
        self._server_states[s_id] = ServerRuntimeState(
            server_id=s_id,
            current_build=srv.current_build,
            latest_build=srv.latest_build,
            last_status=srv.last_status,
        )

  def clear(self) -> None:
    with self._lock:
      self._global_state = AppRuntimeState()
      self._server_states.clear()
