import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from app.core.models import AppConfigModel
from app.main import lifespan


class TestSslVerifyLifespan(unittest.IsolatedAsyncioTestCase):

  async def test_lifespan_ssl_verify_disabled_by_default(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel(ssl_verify=False)

    async def dummy_loop(self):
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        pass

    with patch.dict(os.environ, {}, clear=False), \
         patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls, \
         patch("app.main.logger.warning") as mock_log_warn, \
         patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

      if "SSL_VERIFY" in os.environ:
        del os.environ["SSL_VERIFY"]

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      test_app = FastAPI()
      async with lifespan(test_app):
        # Verify httpx.AsyncClient was initialized with verify=False
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertFalse(kwargs.get("verify"))
        mock_log_warn.assert_called_once_with(
            "SSL verification is disabled (ssl_verify=False). Set ssl_verify=True in settings for verified TLS certificates."
        )

  async def test_lifespan_ssl_verify_enabled_in_config(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel(ssl_verify=True)

    async def dummy_loop(self):
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        pass

    with patch.dict(os.environ, {}, clear=False), \
         patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls, \
         patch("app.main.logger.warning") as mock_log_warn, \
         patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

      if "SSL_VERIFY" in os.environ:
        del os.environ["SSL_VERIFY"]

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      test_app = FastAPI()
      async with lifespan(test_app):
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertTrue(kwargs.get("verify"))
        mock_log_warn.assert_not_called()

  async def test_lifespan_ssl_verify_env_override_true(self):
    mock_repo = MagicMock()
    # Config is False, but env var is True
    mock_repo.load.return_value = AppConfigModel(ssl_verify=False)

    async def dummy_loop(self):
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        pass

    with patch.dict(os.environ, {"SSL_VERIFY": "true"}), \
         patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls, \
         patch("app.main.logger.warning") as mock_log_warn, \
         patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      test_app = FastAPI()
      async with lifespan(test_app):
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertTrue(kwargs.get("verify"))
        mock_log_warn.assert_not_called()

  async def test_lifespan_ssl_verify_env_override_false(self):
    mock_repo = MagicMock()
    # Config is True, but env var is False
    mock_repo.load.return_value = AppConfigModel(ssl_verify=True)

    async def dummy_loop(self):
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        pass

    with patch.dict(os.environ, {"SSL_VERIFY": "0"}), \
         patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls, \
         patch("app.main.logger.warning") as mock_log_warn, \
         patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      test_app = FastAPI()
      async with lifespan(test_app):
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertFalse(kwargs.get("verify"))
        mock_log_warn.assert_called_once_with(
            "SSL verification is disabled (ssl_verify=False). Set ssl_verify=True in settings for verified TLS certificates."
        )

  async def test_lifespan_ssl_verify_env_empty_string_falls_back_to_config(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel(ssl_verify=True)

    async def dummy_loop(self):
      pass

    with patch.dict(os.environ, {"SSL_VERIFY": ""}), \
         patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls, \
         patch("app.main.logger.warning") as mock_log_warn, \
         patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      test_app = FastAPI()
      async with lifespan(test_app):
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertTrue(kwargs.get("verify"))
        mock_log_warn.assert_not_called()

  async def test_lifespan_ssl_verify_env_whitespace_falls_back_to_config(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel(ssl_verify=False)

    async def dummy_loop(self):
      pass

    with patch.dict(os.environ, {"SSL_VERIFY": "   "}), \
         patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls, \
         patch("app.main.logger.warning") as mock_log_warn, \
         patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      test_app = FastAPI()
      async with lifespan(test_app):
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertFalse(kwargs.get("verify"))
        mock_log_warn.assert_called_once()

  async def test_lifespan_ssl_verify_env_various_truthy_strings(self):
    async def dummy_loop(self):
      pass

    for val in ("yes", "on", "1", "TRUE", " true "):
      mock_repo = MagicMock()
      mock_repo.load.return_value = AppConfigModel(ssl_verify=False)

      with patch.dict(os.environ, {"SSL_VERIFY": val}), \
           patch("app.main.ConfigRepository", return_value=mock_repo), \
           patch("app.main.httpx.AsyncClient") as mock_client_cls, \
           patch("app.main.logger.warning") as mock_log_warn, \
           patch("app.main.UpdateOrchestrator.start_background_loop", new=dummy_loop):

        mock_client_instance = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

        test_app = FastAPI()
        async with lifespan(test_app):
          mock_client_cls.assert_called_once()
          _, kwargs = mock_client_cls.call_args
          self.assertTrue(kwargs.get("verify"), f"Expected True for SSL_VERIFY={val}")
          mock_log_warn.assert_not_called()


if __name__ == "__main__":
  unittest.main()

