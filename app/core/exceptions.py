"""Domain-specific exceptions for Pterodactyl Auto-Updater."""

from typing import Optional


class DomainError(Exception):
  """Base exception for all application domain errors."""


class PterodactylApiError(DomainError):
  """Raised when a Pterodactyl Panel API call fails or encounters an error."""

  def __init__(
      self,
      message: str,
      status_code: Optional[int] = None,
      server_id: Optional[str] = None,
      details: Optional[str] = None,
  ):
    super().__init__(message)
    self.status_code = status_code
    self.server_id = server_id
    self.details = details


class SteamApiError(DomainError):
  """Raised when SteamCMD Web API or patch note queries fail."""

  def __init__(self, message: str, app_id: Optional[str] = None):
    super().__init__(message)
    self.app_id = app_id


class A2SQueryError(DomainError):
  """Raised when an A2S UDP query to a game server fails."""


class ConfigurationError(DomainError):
  """Raised when application configuration is invalid or corrupted."""
