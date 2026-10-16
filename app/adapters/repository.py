import asyncio
import json
import logging
import os
import tempfile
import threading
import time
from typing import Optional
from app.core.config import CONFIG_PATH
from app.core.exceptions import ConfigurationError
from app.core.models import AppConfigModel

logger = logging.getLogger("updater.repository")


class ConfigRepository:
  """Thread-safe configuration repository with atomic file persistence."""

  def __init__(self, filepath: str = CONFIG_PATH):
    self.filepath = filepath
    self._lock = threading.RLock()
    self._cached_config: Optional[AppConfigModel] = None

  def load(self) -> AppConfigModel:
    """Loads configuration from disk, falling back to cached state or defaults."""
    with self._lock:
      if os.path.exists(self.filepath):
        try:
          with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            config = AppConfigModel(**data)
            self._cached_config = config.model_copy(deep=True)
            return config
        except Exception as e:
          logger.error(
              f"Error loading {self.filepath}, falling back to defaults or cache: {e}"
          )
          if self._cached_config is not None:
            return self._cached_config.model_copy(deep=True)

      fallback = AppConfigModel()
      self._cached_config = fallback.model_copy(deep=True)
      return fallback

  def save(self, config: AppConfigModel) -> None:
    """Atomically persists configuration to disk using a temporary file and fsync."""
    with self._lock:
      temp_path = None
      try:
        # 1. Validate serialization and JSON integrity prior to disk operations
        payload = config.model_dump_json(indent=2)
        json.loads(payload)

        target_dir = os.path.dirname(os.path.abspath(self.filepath))
        os.makedirs(target_dir, exist_ok=True)

        # 2. Write to temporary file in the same directory to allow atomic rename
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_dir,
            delete=False,
            prefix=".config_tmp_",
        ) as temp_file:
          temp_path = temp_file.name
          temp_file.write(payload)
          temp_file.flush()
          os.fsync(temp_file.fileno())

        # 3. Atomically replace the destination file (with retry for transient Windows file locks)
        for attempt in range(5):
          try:
            os.replace(temp_path, self.filepath)
            break
          except PermissionError:
            if attempt == 4:
              raise
            time.sleep(0.02)
        temp_path = None

        # 4. Update in-memory cache
        self._cached_config = config.model_copy(deep=True)
      except ConfigurationError:
        raise
      except Exception as e:
        logger.error(f"Failed to save configuration to {self.filepath}: {e}")
        raise ConfigurationError(f"Failed to save configuration: {e}") from e
      finally:
        # Clean up temporary file if write or replace was aborted
        if temp_path and os.path.exists(temp_path):
          try:
            os.remove(temp_path)
          except OSError:
            pass

  async def async_save(self, config: AppConfigModel) -> None:
    """Asynchronously saves configuration by executing atomic write in executor."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, self.save, config)
