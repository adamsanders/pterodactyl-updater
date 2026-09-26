import logging
from typing import Optional
from app.core.protocols import ConfigRepositoryProtocol, SteamGateway
from app.services.build_simulator import BuildSimulatorStore

logger = logging.getLogger("updater.steam.simulated")


class SimulatedSteamAdapter:
  """Decorator that intercepts SteamCMD build version queries for targeted servers

  when Test Mode is active, while passing patch notes and untargeted servers directly
  to the real Steam API.
  """

  def __init__(
      self,
      real_steam: SteamGateway,
      simulator_store: BuildSimulatorStore,
      repository: ConfigRepositoryProtocol,
  ):
    self._real_steam = real_steam
    self._simulator_store = simulator_store
    self._repo = repository

  async def get_latest_build(
      self, app_id: str, server_id: Optional[str] = None
  ) -> Optional[str]:
    cfg = self._repo.load()
    if cfg.test_mode and server_id:
      simulated = self._simulator_store.get_simulated_build(server_id)
      if simulated:
        logger.info(
            f"[TEST MITM] Intercepted Steam build query for Server ID"
            f" '{server_id}' (App {app_id}) -> returning simulated build"
            f" '{simulated}'"
        )
        return simulated

    return await self._real_steam.get_latest_build(app_id)

  async def fetch_patchnotes(self, appid: int | str) -> Optional[dict]:
    return await self._real_steam.fetch_patchnotes(appid)