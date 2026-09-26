from typing import Dict, Optional


class BuildSimulatorStore:
  """In-memory store for simulated SteamCMD build IDs during Test Mode, keyed by unique server_id."""

  def __init__(self):
    self._simulated_builds: Dict[str, str] = {}

  def set_simulated_build(self, server_id: str, build_id: str) -> None:
    self._simulated_builds[str(server_id).strip()] = str(build_id).strip()

  def get_simulated_build(self, server_id: str) -> Optional[str]:
    return self._simulated_builds.get(str(server_id).strip())

  def has_simulated_build(self, server_id: str) -> bool:
    return str(server_id).strip() in self._simulated_builds

  def clear_simulated_build(self, server_id: Optional[str] = None) -> None:
    if server_id:
      self._simulated_builds.pop(str(server_id).strip(), None)
    else:
      self._simulated_builds.clear()