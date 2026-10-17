"""Domain-specific exceptions for Pterodactyl Auto-Updater."""

from typing import Optional


class DomainError(Exception):
  """Base exception for all application domain errors."""

  def __init__(self, message: str = "", status_code: Optional[int] = None):
    super().__init__(message)
    self.status_code = status_code


class PterodactylApiError(DomainError):
  """Raised when a Pterodactyl Panel API call fails or encounters an error."""

  def __init__(
      self,
      message: str,
      status_code: Optional[int] = None,
      server_id: Optional[str] = None,
      details: Optional[str] = None,
  ):
    super().__init__(message, status_code=status_code)
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
    super().__init__(message, status_code=status_code or 502)
    self.app_id = app_id


class A2SQueryError(DomainError):
  """Raised when an A2S UDP query to a game server fails."""

  def __init__(
      self,
      message: str,
      server_id: Optional[str] = None,
      status_code: Optional[int] = None,
  ):
    super().__init__(message, status_code=status_code or 504)
    self.server_id = server_id


class ConfigurationError(DomainError):
  """Raised when application configuration is invalid or corrupted."""

  def __init__(self, message: str, status_code: Optional[int] = None):
    super().__init__(message, status_code=status_code or 400)


class NotificationError(DomainError):
  """Raised when a notification dispatch fails."""

  def __init__(
      self,
      message: str,
      status_code: Optional[int] = None,
      details: Optional[str] = None,
  ):
    super().__init__(message, status_code=status_code or 502)
    self.details = details


class UnauthorizedError(DomainError):
  """Raised when authentication or authorization fails."""

  def __init__(
      self,
      message: str = "Unauthorized access to panel",
      status_code: Optional[int] = 401,
      server_id: Optional[str] = None,
  ):
    super().__init__(message, status_code=status_code or 401)
    self.server_id = server_id


class NotFoundError(DomainError):
  """Raised when a requested resource or entity is not found."""

  def __init__(
      self,
      message: str = "Resource not found",
      status_code: Optional[int] = 404,
      server_id: Optional[str] = None,
  ):
    super().__init__(message, status_code=status_code or 404)
    self.server_id = server_id


class ConflictError(DomainError):
  """Raised when an operation conflicts with the current resource state."""

  def __init__(
      self,
      message: str = "Conflict",
      status_code: Optional[int] = 409,
      server_id: Optional[str] = None,
  ):
    super().__init__(message, status_code=status_code or 409)
    self.server_id = server_id


class ValidationError(DomainError):
  """Raised when domain entity or input validation fails."""

  def __init__(
      self,
      message: str = "Validation error",
      status_code: Optional[int] = 400,
      server_id: Optional[str] = None,
  ):
    super().__init__(message, status_code=status_code or 400)
    self.server_id = server_id


class ServerNotFoundError(NotFoundError):
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
    super().__init__(msg, status_code=status_code, server_id=sid)
    self.identifier = sid


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

