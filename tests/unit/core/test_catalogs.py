import dataclasses
import unittest
import warnings

from app.core.catalogs import (
    GameCatalogEntry,
    IGNORED_STEAM_APPIDS,
    SERVER_TO_GAME_APPID,
    GAME_TO_SERVER_APPID,
    POPULAR_DEDICATED_SERVERS,
    PORT_OFFSET_MAP,
    resolve_game_appid,
    resolve_query_port,
)
import app.core.config as config_module


class TestGameCatalogEntry(unittest.TestCase):

  def test_entry_minimal_defaults(self):
    entry = GameCatalogEntry(app_id="12345", name="My Custom Dedicated Server")
    self.assertEqual(entry.app_id, "12345")
    self.assertEqual(entry.name, "My Custom Dedicated Server")
    self.assertEqual(entry.manifest_name, "appmanifest_12345.acf")
    self.assertEqual(entry.default_query_offset, 0)
    self.assertEqual(entry.game, "My Custom Dedicated Server")

  def test_entry_explicit_attributes(self):
    entry = GameCatalogEntry(
        app_id="896660",
        name="Valheim Dedicated Server",
        manifest_name="custom_manifest.acf",
        default_query_offset=1,
        game="Valheim",
    )
    self.assertEqual(entry.app_id, "896660")
    self.assertEqual(entry.name, "Valheim Dedicated Server")
    self.assertEqual(entry.manifest_name, "custom_manifest.acf")
    self.assertEqual(entry.default_query_offset, 1)
    self.assertEqual(entry.game, "Valheim")

  def test_entry_is_frozen(self):
    entry = GameCatalogEntry(app_id="100", name="Immutable Server")
    with self.assertRaises(dataclasses.FrozenInstanceError):
      entry.app_id = "200"

  def test_entry_mapping_interface(self):
    entry = GameCatalogEntry(
        app_id="896660",
        name="Valheim Dedicated Server",
        game="Valheim",
        default_query_offset=1,
    )
    # __getitem__
    self.assertEqual(entry["app_id"], "896660")
    self.assertEqual(entry["name"], "Valheim Dedicated Server")
    self.assertEqual(entry["game"], "Valheim")
    self.assertEqual(entry["default_query_offset"], 1)
    self.assertEqual(entry["manifest_name"], "appmanifest_896660.acf")
    with self.assertRaises(KeyError):
      _ = entry["nonexistent_field"]
    with self.assertRaises(KeyError):
      _ = entry["to_dict"]
    with self.assertRaises(KeyError):
      _ = entry["keys"]

    # get()
    self.assertEqual(entry.get("app_id"), "896660")
    self.assertEqual(entry.get("missing", "fallback"), "fallback")
    self.assertIsNone(entry.get("missing"))
    self.assertIsNone(entry.get("to_dict"))
    self.assertEqual(entry.get("to_dict", "fallback"), "fallback")
    self.assertIsNone(entry.get("keys"))

    # membership & length
    self.assertIn("app_id", entry)
    self.assertIn("name", entry)
    self.assertNotIn("nonexistent", entry)
    self.assertNotIn("to_dict", entry)
    self.assertNotIn("keys", entry)
    self.assertEqual(len(entry), 5)
    self.assertEqual(list(entry.keys()), ["app_id", "name", "manifest_name", "default_query_offset", "game"])

    # dict conversion
    d = dict(entry)
    self.assertIsInstance(d, dict)
    self.assertEqual(d["app_id"], "896660")
    self.assertEqual(d["manifest_name"], "appmanifest_896660.acf")

    # to_dict method
    td = entry.to_dict()
    self.assertIsInstance(td, dict)
    self.assertEqual(td["default_query_offset"], 1)


class TestCatalogsData(unittest.TestCase):

  def test_ignored_steam_appids(self):
    self.assertIsInstance(IGNORED_STEAM_APPIDS, set)
    self.assertIn("1007", IGNORED_STEAM_APPIDS)
    self.assertIn("228980", IGNORED_STEAM_APPIDS)
    self.assertIn("1008", IGNORED_STEAM_APPIDS)
    self.assertIn("1009", IGNORED_STEAM_APPIDS)
    self.assertIn("0", IGNORED_STEAM_APPIDS)

  def test_server_to_game_appid_and_inverse(self):
    self.assertIsInstance(SERVER_TO_GAME_APPID, dict)
    self.assertIsInstance(GAME_TO_SERVER_APPID, dict)
    self.assertEqual(SERVER_TO_GAME_APPID["896660"], "892970")   # Valheim
    self.assertEqual(SERVER_TO_GAME_APPID["2394010"], "1623730") # Palworld
    self.assertEqual(SERVER_TO_GAME_APPID["2278520"], "1203620") # Enshrouded
    self.assertEqual(SERVER_TO_GAME_APPID["258550"], "252490")   # Rust

    # Inverse mapping
    for srv_id, game_id in SERVER_TO_GAME_APPID.items():
      self.assertEqual(GAME_TO_SERVER_APPID[game_id], srv_id)

  def test_popular_dedicated_servers(self):
    self.assertIsInstance(POPULAR_DEDICATED_SERVERS, list)
    self.assertGreater(len(POPULAR_DEDICATED_SERVERS), 20)
    seen_appids = set()
    for srv in POPULAR_DEDICATED_SERVERS:
      self.assertIsInstance(srv, GameCatalogEntry)
      self.assertTrue(srv.app_id)
      self.assertTrue(srv.name)
      self.assertTrue(srv.manifest_name)
      self.assertNotIn(srv.app_id, seen_appids, f"Duplicate app_id {srv.app_id}")
      seen_appids.add(srv.app_id)

      # Subscript access works
      self.assertEqual(srv["app_id"], srv.app_id)
      self.assertEqual(srv["name"], srv.name)

    # Check known entry with offset
    valheim = next(s for s in POPULAR_DEDICATED_SERVERS if s.app_id == "896660")
    self.assertEqual(valheim.default_query_offset, 1)

  def test_port_offset_map(self):
    self.assertIsInstance(PORT_OFFSET_MAP, dict)
    self.assertEqual(PORT_OFFSET_MAP[896660], 1)
    self.assertEqual(PORT_OFFSET_MAP[2278520], 1)
    self.assertEqual(PORT_OFFSET_MAP[1829350], 1)
    self.assertEqual(PORT_OFFSET_MAP[294420], 1)


class TestCatalogResolvers(unittest.TestCase):

  def test_resolve_game_appid_mapped(self):
    self.assertEqual(resolve_game_appid("896660"), "892970")
    self.assertEqual(resolve_game_appid(896660), "892970")
    self.assertEqual(resolve_game_appid(" 2394010 "), "1623730")

  def test_resolve_game_appid_unmapped(self):
    self.assertEqual(resolve_game_appid("999999"), "999999")
    self.assertEqual(resolve_game_appid(999999), "999999")
    self.assertEqual(resolve_game_appid("custom_game"), "custom_game")
    self.assertEqual(resolve_game_appid(None), "")
    self.assertEqual(resolve_game_appid(""), "")

  def test_resolve_query_port_with_nonzero_offset(self):
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset=2), 2458)
    self.assertEqual(resolve_query_port("896660", 2456, query_port_offset=10), 2466)
    self.assertEqual(resolve_query_port(999999, 7777, query_port_offset=3), 7780)
    self.assertEqual(resolve_query_port("custom", 8000, query_port_offset=5), 8005)

  def test_resolve_query_port_with_negative_offset(self):
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset=-1), 2455)
    self.assertEqual(resolve_query_port("custom", 10000, query_port_offset=-50), 9950)

  def test_resolve_query_port_zero_offset_falls_back_to_port_offset_map(self):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always", DeprecationWarning)
      self.assertEqual(resolve_query_port(896660, 2456, query_port_offset=0), 2457)
      self.assertEqual(resolve_query_port("896660", 2456), 2457)
      self.assertEqual(resolve_query_port(2278520, 15636, query_port_offset=0), 15637)
      self.assertEqual(resolve_query_port(1829350, 9876, query_port_offset=0), 9877)
      self.assertEqual(resolve_query_port(294420, 26900, query_port_offset=0), 26901)
      self.assertTrue(any(issubclass(item.category, DeprecationWarning) for item in w))
      self.assertIn("PORT_OFFSET_MAP fallback is deprecated", str(w[0].message))

  def test_resolve_query_port_zero_offset_unmapped_returns_game_port(self):
    self.assertEqual(resolve_query_port(2394010, 8211, query_port_offset=0), 8211)
    self.assertEqual(resolve_query_port(999999, 7777, query_port_offset=0), 7777)
    self.assertEqual(resolve_query_port("invalid_appid", 7777, query_port_offset=0), 7777)

  def test_resolve_query_port_falsy_game_port(self):
    self.assertEqual(resolve_query_port(896660, 0, query_port_offset=1), 0)
    self.assertEqual(resolve_query_port(896660, None, query_port_offset=1), 0)
    self.assertEqual(resolve_query_port(896660, -100, query_port_offset=1), 0)

  def test_resolve_query_port_string_args(self):
    self.assertEqual(resolve_query_port(896660, "2456", query_port_offset=2), 2458)
    self.assertEqual(resolve_query_port(896660, " 2456 ", query_port_offset=" 3 "), 2459)
    self.assertEqual(resolve_query_port(896660, "invalid_port", query_port_offset=1), 0)
    with warnings.catch_warnings(record=True):
      warnings.simplefilter("always", DeprecationWarning)
      self.assertEqual(resolve_query_port(896660, 2456, query_port_offset="invalid"), 2457)

  def test_resolve_query_port_out_of_range_clamping(self):
    self.assertEqual(resolve_query_port(896660, 65530, query_port_offset=10), 0)
    self.assertEqual(resolve_query_port(896660, 1000, query_port_offset=-2000), 0)


class TestConfigReExportsBackwardCompatibility(unittest.TestCase):

  def test_config_re_exports_identical_objects(self):
    self.assertIs(config_module.GameCatalogEntry, GameCatalogEntry)
    self.assertIs(config_module.IGNORED_STEAM_APPIDS, IGNORED_STEAM_APPIDS)
    self.assertIs(config_module.SERVER_TO_GAME_APPID, SERVER_TO_GAME_APPID)
    self.assertIs(config_module.GAME_TO_SERVER_APPID, GAME_TO_SERVER_APPID)
    self.assertIs(config_module.POPULAR_DEDICATED_SERVERS, POPULAR_DEDICATED_SERVERS)
    self.assertIs(config_module.PORT_OFFSET_MAP, PORT_OFFSET_MAP)
    self.assertIs(config_module.resolve_game_appid, resolve_game_appid)
    self.assertIs(config_module.resolve_query_port, resolve_query_port)


if __name__ == "__main__":
  unittest.main()
