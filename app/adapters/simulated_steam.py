import logging
from typing import Optional, Union
from app.core.models import SteamPatchNotes, SteamSearchResult
from app.core.protocols import (
    BuildSimulatorProtocol,
    ConfigRepositoryProtocol,
    SteamGateway,
)

logger = logging.getLogger("updater.steam.simulated")


class SimulatedSteamAdapter:
  """Decorator that intercepts SteamCMD build version queries for targeted servers

  when Test Mode is active, while passing patch notes and untargeted servers directly
  to the real Steam API.
  """

  def __init__(
      self,
      real_steam: SteamGateway,
      simulator_store: BuildSimulatorProtocol,
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

  async def fetch_patchnotes(
      self, appid: int | str
  ) -> Optional[Union[SteamPatchNotes, dict]]:
    return await self._real_steam.fetch_patchnotes(appid)

  async def search_games(self, query: str) -> list[SteamSearchResult]:
    res = await self._real_steam.search_games(query)
    return [
        r if isinstance(r, SteamSearchResult) else SteamSearchResult(**r)
        for r in res
    ]
