import unittest
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.adapters.pterodactyl import PterodactylAdapter


class TestPterodactylAdapterDetailsDetection(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.mock_client = AsyncMock(spec=httpx.AsyncClient)
    self.adapter = PterodactylAdapter(self.mock_client)

  async def test_detect_server_details_from_startup_variables(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {
            "data": [
                {
                    "attributes": {
                        "env_variable": "APP_ID",
                        "server_value": "2230650",
                    }
                }
            ],
            "meta": {"startup_command": "./server"},
        }
      elif url.endswith("/files/list"):
        resp.json.return_value = {"data": []}
      else:
        resp.json.return_value = {
            "attributes": {"name": "My Enshrouded Dedicated Server"}
        }
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-1"
    )
    self.assertEqual(details["app_id"], "2230650")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2230650.acf")
    self.assertEqual(details["name"], "My Enshrouded Dedicated Server")

  async def test_detect_server_details_from_manifest_file(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {"data": [], "meta": {"startup_command": ""}}
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [
                {"attributes": {"name": "appmanifest_2394010.acf"}}
            ]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Palworld Server"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-2"
    )
    self.assertEqual(details["app_id"], "2394010")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2394010.acf")
    self.assertEqual(details["name"], "Palworld Server")

  async def test_detect_server_details_from_server_name(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {"data": [], "meta": {"startup_command": ""}}
      elif "/files/list" in url:
        resp.json.return_value = {"data": []}
      else:
        resp.json.return_value = {"attributes": {"name": "Official Valheim Realm"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-3"
    )
    self.assertEqual(details["app_id"], "896660")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_896660.acf")
    self.assertEqual(details["name"], "Official Valheim Realm")

  async def test_get_local_build_empty_manifest_or_server_id_returns_clean_error(self):
    build, err = await self.adapter.get_local_build(
        "http://panel.test", "key", "", ""
    )
    self.assertIsNone(build)
    self.assertIn("not configured", err)

  async def test_detect_server_details_ignores_1007_manifest_and_picks_game_manifest(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {"data": [], "meta": {"startup_command": ""}}
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [
                {"attributes": {"name": "appmanifest_1007.acf"}},
                {"attributes": {"name": "appmanifest_2278520.acf"}},
            ]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Enshrouded Realm"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-enshrouded"
    )
    self.assertEqual(details["app_id"], "2278520")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2278520.acf")

  async def test_detect_server_details_from_startup_command_flag(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {
            "data": [],
            "meta": {
                "startup_command": "steamcmd +force_install_dir /home/container +login anonymous +app_update 2278520 validate +quit"
            },
        }
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [{"attributes": {"name": "appmanifest_1007.acf"}}]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Enshrouded Server"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-enshrouded"
    )
    self.assertEqual(details["app_id"], "2278520")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2278520.acf")

  async def test_detect_server_details_preserves_detected_appid_when_1007_is_in_files(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {
            "data": [
                {"attributes": {"env_variable": "STEAM_APPID", "server_value": "896660"}}
            ],
            "meta": {"startup_command": ""},
        }
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [
                {"attributes": {"name": "appmanifest_1007.acf"}},
                {"attributes": {"name": "appmanifest_896660.acf"}},
            ]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Valheim Server"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-valheim"
    )
    self.assertEqual(details["app_id"], "896660")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_896660.acf")


if __name__ == "__main__":
  unittest.main()
