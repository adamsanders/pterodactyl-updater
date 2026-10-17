from typing import Any, Optional, Union
from app.core.models import NotificationPreview


class WebhookPreviewStore:

  def __init__(self):
    self._preview: Optional[Any] = None

  def set_preview(self, preview: Any) -> None:
    self._preview = preview

  def get_preview(self) -> Optional[Any]:
    return self._preview

  def clear(self) -> None:
    self._preview = None

  def consume_preview(self) -> Optional[Any]:
    preview = self._preview
    self._preview = None
    return preview