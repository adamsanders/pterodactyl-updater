from typing import Optional
from app.core.models import WebhookPreview


class WebhookPreviewStore:

  def __init__(self):
    self._preview: Optional[WebhookPreview] = None

  def set_preview(self, preview: WebhookPreview) -> None:
    self._preview = preview

  def get_preview(self) -> Optional[WebhookPreview]:
    return self._preview

  def clear(self) -> None:
    self._preview = None

  def consume_preview(self) -> Optional[WebhookPreview]:
    preview = self._preview
    self._preview = None
    return preview