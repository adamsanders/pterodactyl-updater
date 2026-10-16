import json
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.models import AppConfigModel, ServerModel
from app.services.runtime_state import RuntimeStateStore
from app.services.status_service import StatusAggregationService
from app.services.updater import UpdateOrchestrator


class TestRuntimeStateStore(unittest.TestCase):

  def setUp(self):
    self.store = RuntimeStateStore()

  def test_default_state(self):
    g_state = self.store.get_global_state()
    self.assertEqual(g_state.last_check, "Never")
    self.assertEqual(g_state.last_status, "Idle")

    s_state = self.store.get_server_state("srv1")
    self.assertEqual(s_state.server_id, "srv1")
    self.assertEqual(s_state.current_build, "Unknown")
    self.assertEqual(s_state.latest_build, "Unknown")
    self.assertEqual(s_state.last_status, "Idle")

  def test_update_global_state(self):
    updated = self.store.update_global_state(last_check="2026-10-16 12:00:00")
    self.assertEqual(updated.last_check, "2026-10-16 12:00:00")
    self.assertEqual(updated.last_status, "Idle")

    updated2 = self.store.update_global_state(last_status="Checked 2 servers")
    self.assertEqual(updated2.last_check, "2026-10-16 12:00:00")
    self.assertEqual(updated2.last_status, "Checked 2 servers")

  def test_update_server_state(self):
    self.store.update_server_state(
        "srv1", current_build="100", latest_build="200", last_status="Update Available"
    )
    s_state = self.store.get_server_state("srv1")
    self.assertEqual(s_state.current_build, "100")
    self.assertEqual(s_state.latest_build, "200")
    self.assertEqual(s_state.last_status, "Update Available")

    # Partial update preserves other fields
    self.store.update_server_state("srv1", last_status="Up to date")
    s_state2 = self.store.get_server_state("srv1")
    self.assertEqual(s_state2.current_build, "100")
    self.assertEqual(s_state2.latest_build, "200")
    self.assertEqual(s_state2.last_status, "Up to date")

  def test_seed_from_config(self):
    cfg = AppConfigModel(
        last_check="2026-10-15 10:00:00",
        last_status="Initial Status",
        servers=[
            ServerModel(
                server_id="srv_a",
                current_build="555",
                latest_build="666",
                last_status="Running smoothly",
            )
        ],
    )
    self.store.seed_from_config(cfg)

    g_state = self.store.get_global_state()
    self.assertEqual(g_state.last_check, "2026-10-15 10:00:00")
    self.assertEqual(g_state.last_status, "Initial Status")

    s_state = self.store.get_server_state("srv_a")
    self.assertEqual(s_state.current_build, "555")
    self.assertEqual(s_state.latest_build, "666")
    self.assertEqual(s_state.last_status, "Running smoothly")

  def test_clear(self):
    self.store.update_global_state("now", "running")
    self.store.update_server_state("srv1", "1", "2", "status")
    self.store.clear()

    g_state = self.store.get_global_state()
    self.assertEqual(g_state.last_check, "Never")
    self.assertEqual(g_state.last_status, "Idle")

    s_state = self.store.get_server_state("srv1")
    self.assertEqual(s_state.current_build, "Unknown")

  def test_thread_safe_concurrent_access(self):
    threads = []
    errors = []

    def worker(worker_id: int):
      try:
        for i in range(100):
          self.store.update_global_state(
              last_check=f"time_{worker_id}_{i}", last_status=f"status_{worker_id}"
          )
          self.store.update_server_state(
              f"srv_{worker_id}",
              current_build=str(i),
              latest_build=str(i + 1),
              last_status="active",
          )
          _ = self.store.get_global_state()
          _ = self.store.get_server_state(f"srv_{worker_id}")
      except Exception as e:
        errors.append(e)

    for w in range(10):
      t = threading.Thread(target=worker, args=(w,))
      threads.append(t)
      t.start()

    for t in threads:
      t.join()

    self.assertEqual(len(errors), 0)
    all_states = self.store.get_all_server_states()
    self.assertEqual(len(all_states), 10)


class TestConfigDecoupling(unittest.TestCase):

  def test_config_serialization_excludes_transient_fields(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="ptlc_test",
        last_check="2026-10-16 12:00:00",
        last_status="Active Check",
        servers=[
            ServerModel(
                name="Valheim",
                server_id="srv1",
                current_build="12345",
                latest_build="67890",
                last_status="Up to date",
            )
        ],
    )

    serialized = cfg.model_dump_json()
    data = json.loads(serialized)

    # Transient fields MUST be excluded from serialized JSON persistence
    self.assertNotIn("last_check", data)
    self.assertNotIn("last_status", data)
    self.assertIn("panel_url", data)
    self.assertIn("api_key", data)

    server_data = data["servers"][0]
    self.assertNotIn("current_build", server_data)
    self.assertNotIn("latest_build", server_data)
    self.assertNotIn("last_status", server_data)
    self.assertIn("server_id", server_data)
    self.assertIn("name", server_data)

  def test_server_model_still_exposes_attributes(self):
    srv = ServerModel(
        name="Enshrouded",
        server_id="srv2",
        current_build="100",
        latest_build="200",
        last_status="Updating",
    )
    # Python attribute access remains 100% backward-compatible
    self.assertEqual(srv.current_build, "100")
    self.assertEqual(srv.latest_build, "200")
    self.assertEqual(srv.last_status, "Updating")


class TestServiceRuntimeStateIntegration(unittest.IsolatedAsyncioTestCase):

  async def test_run_update_check_updates_runtime_state_and_avoids_repo_save(self):
    repo = MagicMock()
    srv = ServerModel(name="Valheim", server_id="srv1", app_id="896660")
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[srv],
    )
    repo.load.return_value = cfg

    ptero = AsyncMock()
    ptero.get_server_name.return_value = ("Valheim", None)
    ptero.get_power_state.return_value = "running"
    ptero.get_local_build.return_value = ("999", None)
    ptero.consume_startup_transition = MagicMock(return_value=False)

    steam = AsyncMock()
    steam.get_latest_build.return_value = "999"

    countdown = MagicMock()
    countdown.is_running.return_value = False

    runtime_state = RuntimeStateStore()

    orchestrator = UpdateOrchestrator(
        repository=repo,
        ptero=ptero,
        steam=steam,
        countdown=countdown,
        runtime_state=runtime_state,
    )

    await orchestrator.run_update_check()

    # Runtime state must be updated in memory
    g_state = runtime_state.get_global_state()
    self.assertNotEqual(g_state.last_check, "Never")
    self.assertIn("Checked 1 server(s) successfully", g_state.last_status)

    s_state = runtime_state.get_server_state("srv1")
    self.assertEqual(s_state.current_build, "999")
    self.assertEqual(s_state.latest_build, "999")
    self.assertEqual(s_state.last_status, "Up to date")

    # repo.save MUST NOT be called during periodic background monitoring!
    repo.save.assert_not_called()

  async def test_status_service_uses_runtime_state_and_avoids_disk_save(self):
    repo = MagicMock()
    srv = ServerModel(name="Valheim", server_id="srv1", app_id="896660")
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[srv],
    )
    repo.load.return_value = cfg

    ptero = AsyncMock()
    ptero.get_external_ip.return_value = "1.2.3.4"
    ptero.get_power_state.return_value = "offline"
    ptero.consume_startup_transition = MagicMock(return_value=False)
    ptero.get_server_allocation.return_value = (None, None)

    countdown = MagicMock()
    countdown.is_running.return_value = True
    countdown.get_target.return_value = 0.0
    countdown.get_remaining.return_value = 0

    preview_store = MagicMock()
    preview_store.get_preview.return_value = None

    runtime_state = RuntimeStateStore()
    orchestrator = UpdateOrchestrator(
        repository=repo,
        ptero=ptero,
        steam=AsyncMock(),
        countdown=countdown,
        runtime_state=runtime_state,
    )
    a2s = AsyncMock()


    # Background lifecycle monitor detects power change and updates ephemeral runtime state
    await orchestrator.monitor_server_lifecycle()

    service = StatusAggregationService(
        repository=repo,
        ptero=ptero,
        countdown=countdown,
        preview_store=preview_store,
        a2s=a2s,
        runtime_state=runtime_state,
    )

    snapshot = await service.get_status_snapshot()

    # Status in runtime_state must reflect the offline power cancellation
    s_state = runtime_state.get_server_state("srv1")
    self.assertIn("Manual offline detected", s_state.last_status)
    self.assertEqual(snapshot["servers"][0]["last_status"], s_state.last_status)

    # Disk repo save MUST NOT be called during an HTTP GET query poll when runtime_state is present!
    repo.save.assert_not_called()



if __name__ == "__main__":
  unittest.main()
