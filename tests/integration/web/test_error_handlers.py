import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import DomainError, PterodactylApiError, ServerNotFoundError
from app.main import domain_error_handler


class TestDomainErrorBoundary(unittest.TestCase):

  def test_domain_error_handled_by_fastapi(self):
    test_app = FastAPI()
    test_app.add_exception_handler(DomainError, domain_error_handler)

    # Create a test endpoint on the isolated test app that raises a DomainError
    @test_app.get("/test-error-boundary")
    async def trigger_domain_error():
      raise PterodactylApiError("Unauthorized access to panel", status_code=401, server_id="srv-1")

    client = TestClient(test_app, raise_server_exceptions=False)
    res = client.get("/test-error-boundary")
    self.assertEqual(res.status_code, 401)
    body = res.json()
    self.assertEqual(body.get("status"), "error")
    self.assertEqual(body.get("error"), "PterodactylApiError")
    self.assertIn("Unauthorized access to panel", body.get("message", ""))

  def test_server_not_found_handled_by_fastapi(self):
    test_app = FastAPI()
    test_app.add_exception_handler(DomainError, domain_error_handler)

    @test_app.get("/test-server-not-found")
    async def trigger_not_found():
      raise ServerNotFoundError("Target server not configured", server_id="unknown")

    client = TestClient(test_app, raise_server_exceptions=False)
    res = client.get("/test-server-not-found")
    self.assertEqual(res.status_code, 404)
    body = res.json()
    self.assertEqual(body.get("status"), "error")
    self.assertEqual(body.get("error"), "ServerNotFoundError")
    self.assertEqual(body.get("message"), "Target server not configured")


if __name__ == "__main__":
  unittest.main()
