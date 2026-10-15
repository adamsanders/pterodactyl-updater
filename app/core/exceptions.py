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

  def __init__(
      self,
      message: str,
      app_id: Optional[str] = None,
      status_code: Optional[int] = None,
  ):
    super().__init__(message)
    self.app_id = app_id
    self.status_code = status_code or 502


class A2SQueryError(DomainError):
  """Raised when an A2S UDP query to a game server fails."""

  def __init__(
      self,
      message: str,
      server_id: Optional[str] = None,
      status_code: Optional[int] = None,
  ):
    super().__init__(message)
    self.server_id = server_id
    self.status_code = status_code or 504


class ConfigurationError(DomainError):
  """Raised when application configuration is invalid or corrupted."""

  def __init__(self, message: str, status_code: Optional[int] = None):
    super().__init__(message)
    self.status_code = status_code or 400


class ServerNotFoundError(DomainError):
  """Raised when a targeted server identifier does not match any configured server."""

  def __init__(
      self,
      message_or_id: str,
      server_id: Optional[str] = None,
      status_code: int = 404,
  ):
    sid = server_id or message_or_id
    msg = (
        message_or_id
        if " " in message_or_id
        else f"Server '{message_or_id}' not found."
    )
    super().__init__(msg)
    self.identifier = sid
    self.server_id = sid
    self.status_code = status_code


class InvalidPowerActionError(DomainError):
  """Raised when an invalid power signal is requested."""

  def __init__(
      self,
      action_or_msg: str,
      action: Optional[str] = None,
      status_code: int = 400,
  ):
    act = action or action_or_msg
    msg = (
        action_or_msg
        if " " in action_or_msg
        else f"Invalid power action '{action_or_msg}'."
    )
    super().__init__(msg)
    self.action = act
    self.status_code = status_code


class SimulationError(DomainError):
  """Raised when a Steam game build update simulation cannot be executed."""

  def __init__(
      self,
      message: str,
      server_id: Optional[str] = None,
      status_code: int = 400,
  ):
    super().__init__(message)
    self.server_id = server_id
    self.status_code = status_code

