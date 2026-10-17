import asyncio
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.adapters.repository import ConfigRepository
from app.core.exceptions import ConfigurationError
from app.core.models import AppConfigModel, ServerModel


class TestConfigRepository(unittest.TestCase):

  def setUp(self):
    self.test_dir = tempfile.mkdtemp(prefix="repo_test_")
    self.config_file = os.path.join(self.test_dir, "config.json")
    self.repo = ConfigRepository(filepath=self.config_file)

  def tearDown(self):
    shutil.rmtree(self.test_dir, ignore_errors=True)

  def test_load_missing_file_returns_default(self):
    cfg = self.repo.load()
    self.assertIsInstance(cfg, AppConfigModel)
    self.assertEqual(cfg.check_interval, 15)
    self.assertEqual(len(cfg.servers), 0)

  def test_save_and_load_roundtrip(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="ptlc_testkey",
        check_interval=5,
        discord_webhook="https://discord.com/webhook",
        test_mode=True,
        servers=[ServerModel(name="Valheim 1", server_id="srv_valheim_1")],
    )
    self.repo.save(cfg)

    loaded = self.repo.load()
    self.assertEqual(loaded.panel_url, "http://panel.test")
    self.assertEqual(loaded.api_key, "ptlc_testkey")
    self.assertEqual(loaded.check_interval, 5)
    self.assertTrue(loaded.test_mode)
    self.assertEqual(len(loaded.servers), 1)
    self.assertEqual(loaded.servers[0].name, "Valheim 1")
    self.assertEqual(loaded.servers[0].server_id, "srv_valheim_1")

  def test_atomic_save_leaves_no_temp_files(self):
    cfg = AppConfigModel(panel_url="http://panel.test")
    self.repo.save(cfg)

    files = os.listdir(self.test_dir)
    self.assertIn("config.json", files)
    temp_files = [f for f in files if f.startswith(".config_tmp_")]
    self.assertEqual(len(temp_files), 0)

  def test_atomic_save_failure_leaves_original_intact_and_cleans_temp(self):
    original_cfg = AppConfigModel(panel_url="http://original.test")
    self.repo.save(original_cfg)

    new_cfg = AppConfigModel(panel_url="http://should_fail.test")
    with patch("os.replace", side_effect=OSError("Simulated disk full or permission error")):
      with self.assertRaises(ConfigurationError) as ctx:
        self.repo.save(new_cfg)
      self.assertIn("Failed to save configuration", str(ctx.exception))

    # Verify original file content is completely intact
    with open(self.config_file, "r", encoding="utf-8") as f:
      disk_data = json.load(f)
    self.assertEqual(disk_data["panel_url"], "http://original.test")

    # Verify temporary files were cleaned up
    files = os.listdir(self.test_dir)
    temp_files = [f for f in files if f.startswith(".config_tmp_")]
    self.assertEqual(len(temp_files), 0)

  def test_atomic_save_permission_error_raises_configuration_error(self):
    cfg = AppConfigModel(panel_url="http://perm_error.test")
    with patch("os.makedirs", side_effect=PermissionError("Permission denied")):
      with self.assertRaises(ConfigurationError) as ctx:
        self.repo.save(cfg)
      self.assertIn("Permission denied", str(ctx.exception))

  def test_atomic_save_serialization_error_raises_configuration_error(self):
    cfg = AppConfigModel(panel_url="http://serialization_err.test")
    with patch.object(AppConfigModel, "model_dump_json", side_effect=TypeError("Non-serializable object")):
      with self.assertRaises(ConfigurationError) as ctx:
        self.repo.save(cfg)
      self.assertIn("Failed to save configuration", str(ctx.exception))
      self.assertIn("Non-serializable object", str(ctx.exception))

  def test_async_save_propagates_configuration_error(self):
    cfg = AppConfigModel(panel_url="http://async_fail.test")
    with patch("os.replace", side_effect=OSError("Disk write failed")):
      with self.assertRaises(ConfigurationError) as ctx:
        asyncio.run(self.repo.async_save(cfg))
      self.assertIn("Failed to save configuration", str(ctx.exception))


  def test_corrupt_file_on_disk_falls_back_to_cache(self):
    # Establish cached state
    cfg = AppConfigModel(panel_url="http://known_good.test")
    self.repo.save(cfg)

    # Corrupt the file on disk directly
    with open(self.config_file, "w", encoding="utf-8") as f:
      f.write("{ invalid json corrupted content ...")

    # load() should log error and return cached good config
    loaded = self.repo.load()
    self.assertEqual(loaded.panel_url, "http://known_good.test")

  def test_concurrent_saves_and_loads(self):
    errors = []

    def worker(worker_id: int):
      try:
        for i in range(10):
          cfg = AppConfigModel(
              panel_url=f"http://panel_{worker_id}_{i}.test",
              check_interval=(i % 10) + 1,
              servers=[ServerModel(name=f"Server {worker_id}", server_id=f"id_{worker_id}")],
          )
          self.repo.save(cfg)
          loaded = self.repo.load()
          self.assertTrue(loaded.panel_url.startswith("http://panel_"))
      except Exception as exc:
        errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
      t.start()
    for t in threads:
      t.join()

    self.assertEqual(errors, [])
    # Verify final state is valid JSON and loadable
    final = self.repo.load()
    self.assertIsInstance(final, AppConfigModel)

  def test_ssl_verify_persistence_roundtrip_and_legacy_default(self):
    # 1. Roundtrip with ssl_verify=True
    cfg_true = AppConfigModel(panel_url="https://secure.panel", ssl_verify=True)
    self.repo.save(cfg_true)
    loaded_true = self.repo.load()
    self.assertTrue(loaded_true.ssl_verify)

    # 2. Roundtrip with ssl_verify=False
    cfg_false = AppConfigModel(panel_url="https://insecure.panel", ssl_verify=False)
    self.repo.save(cfg_false)
    loaded_false = self.repo.load()
    self.assertFalse(loaded_false.ssl_verify)

    # 3. Legacy JSON file without ssl_verify key defaults to False
    legacy_json = {
        "panel_url": "http://legacy.panel",
        "api_key": "legacy_key",
        "check_interval": 15,
        "servers": [],
    }
    with open(self.config_file, "w", encoding="utf-8") as f:
      json.dump(legacy_json, f)

    loaded_legacy = self.repo.load()
    self.assertFalse(loaded_legacy.ssl_verify)
    self.assertEqual(loaded_legacy.panel_url, "http://legacy.panel")

  def test_async_save_roundtrip_persistence(self):
    cfg = AppConfigModel(
        panel_url="https://async.panel",
        api_key="async_key",
        check_interval=10,
        servers=[ServerModel(name="Async Server", server_id="srv_async")],
    )
    asyncio.run(self.repo.async_save(cfg))

    loaded = self.repo.load()
    self.assertEqual(loaded.panel_url, "https://async.panel")
    self.assertEqual(loaded.api_key, "async_key")
    self.assertEqual(loaded.check_interval, 10)
    self.assertEqual(len(loaded.servers), 1)
    self.assertEqual(loaded.servers[0].name, "Async Server")

    # Verify no leftover temporary files
    files = os.listdir(self.test_dir)
    temp_files = [f for f in files if f.startswith(".config_tmp_")]
    self.assertEqual(len(temp_files), 0)

  def test_async_save_offloads_to_thread(self):
    cfg = AppConfigModel(panel_url="https://offload.test")
    with patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
      asyncio.run(self.repo.async_save(cfg))
      mock_to_thread.assert_called_once_with(self.repo.save, cfg)

  def test_async_save_propagates_serialization_error(self):
    cfg = AppConfigModel(panel_url="http://async_serial_fail.test")
    with patch.object(AppConfigModel, "model_dump_json", side_effect=TypeError("Cannot serialize")):
      with self.assertRaises(ConfigurationError) as ctx:
        asyncio.run(self.repo.async_save(cfg))
      self.assertIn("Failed to save configuration", str(ctx.exception))

  def test_async_save_propagates_replace_error_and_cleans_temp(self):
    original_cfg = AppConfigModel(panel_url="http://async_original.test")
    self.repo.save(original_cfg)

    new_cfg = AppConfigModel(panel_url="http://async_should_fail.test")
    with patch("os.replace", side_effect=OSError("Disk failure")):
      with self.assertRaises(ConfigurationError) as ctx:
        asyncio.run(self.repo.async_save(new_cfg))
      self.assertIn("Failed to save configuration", str(ctx.exception))

    loaded = self.repo.load()
    self.assertEqual(loaded.panel_url, "http://async_original.test")

    # Verify temp files cleaned up
    files = os.listdir(self.test_dir)
    temp_files = [f for f in files if f.startswith(".config_tmp_")]
    self.assertEqual(len(temp_files), 0)

  def test_interleaved_sync_and_async_save_concurrency(self):
    errors = []

    async def async_worker(wid: int):
      try:
        for i in range(5):
          cfg = AppConfigModel(
              panel_url=f"http://async_{wid}_{i}.test",
              check_interval=i + 1,
          )
          await self.repo.async_save(cfg)
      except Exception as e:
        errors.append(e)

    def sync_worker(wid: int):
      try:
        for i in range(5):
          cfg = AppConfigModel(
              panel_url=f"http://sync_{wid}_{i}.test",
              check_interval=i + 1,
          )
          self.repo.save(cfg)
      except Exception as e:
        errors.append(e)

    async def main_runner():
      threads = [threading.Thread(target=sync_worker, args=(i,)) for i in range(3)]
      for t in threads:
        t.start()
      await asyncio.gather(*[async_worker(i) for i in range(3)])
      for t in threads:
        t.join()

    asyncio.run(main_runner())
    self.assertEqual(errors, [])
    final = self.repo.load()
    self.assertIsInstance(final, AppConfigModel)

  def test_async_save_retries_on_transient_permission_error_and_succeeds(self):
    cfg = AppConfigModel(panel_url="http://retry_success.test")
    original_replace = os.replace
    attempts = 0

    def mock_replace(src, dst):
      nonlocal attempts
      attempts += 1
      if attempts < 3:
        raise PermissionError("Simulated transient Windows file lock")
      return original_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
      asyncio.run(self.repo.async_save(cfg))

    self.assertEqual(attempts, 3)
    loaded = self.repo.load()
    self.assertEqual(loaded.panel_url, "http://retry_success.test")


if __name__ == "__main__":
  unittest.main()

