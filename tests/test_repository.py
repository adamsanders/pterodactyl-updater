import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.adapters.repository import ConfigRepository
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
      self.repo.save(new_cfg)

    # Verify original file content is completely intact
    with open(self.config_file, "r", encoding="utf-8") as f:
      disk_data = json.load(f)
    self.assertEqual(disk_data["panel_url"], "http://original.test")

    # Verify temporary files were cleaned up
    files = os.listdir(self.test_dir)
    temp_files = [f for f in files if f.startswith(".config_tmp_")]
    self.assertEqual(len(temp_files), 0)

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


if __name__ == "__main__":
  unittest.main()
