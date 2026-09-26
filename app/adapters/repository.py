import json
import logging
import os
from app.core.config import CONFIG_PATH
from app.core.models import AppConfigModel

logger = logging.getLogger("updater.repository")


class ConfigRepository:

  def __init__(self, filepath: str = CONFIG_PATH):
    self.filepath = filepath

  def load(self) -> AppConfigModel:
    if os.path.exists(self.filepath):
      try:
        with open(self.filepath, "r", encoding="utf-8") as f:
          data = json.load(f)
          return AppConfigModel(**data)
      except Exception as e:
        logger.error(
            f"Error loading {self.filepath}, falling back to defaults: {e}"
        )
    return AppConfigModel()

  def save(self, config: AppConfigModel) -> None:
    try:
      os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
      with open(self.filepath, "w", encoding="utf-8") as f:
        f.write(config.model_dump_json(indent=2))
    except Exception as e:
      logger.error(f"Failed to save configuration to {self.filepath}: {e}")