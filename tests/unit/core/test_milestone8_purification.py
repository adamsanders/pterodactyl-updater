"""Unit tests verifying Milestone 8 Core Domain Purification & Clean Error Architecture."""

import unittest
import warnings

from app.core.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    PterodactylApiError,
    ServerNotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.models import (
    LocalBuildResult,
    OperationResult,
    ServerModel,
    ServerNameResult,
    ServerUpdateStatus,
)
from app.web.schemas import (
    SettingsUpdateDTO,
    SingleServerSaveRequest,
    WebhookPreview,
)


class TestDomainPurity(unittest.TestCase):
    """Verifies ServerModel has no mutable private attributes and emits DeprecationWarning."""

    def test_server_model_has_no_private_attrs(self):
        # Verify private attributes _current_build, _latest_build, _last_status are purged
        private_attrs = getattr(ServerModel, "__private_attributes__", {})
        self.assertNotIn("_current_build", private_attrs)
        self.assertNotIn("_latest_build", private_attrs)
        self.assertNotIn("_last_status", private_attrs)

    def test_server_model_deprecation_property_access(self):
        srv = ServerModel(
            server_id="test-srv",
            name="Test Server",
            app_id="12345",
            manifest_path="manifest.acf",
            current_build="100",
            latest_build="200",
        )

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            c_build = srv.current_build
            l_build = srv.latest_build
            status = srv.last_status

            self.assertEqual(c_build, "100")
            self.assertEqual(l_build, "200")
            self.assertEqual(status, ServerUpdateStatus.IDLE)

            prop_warnings = [
                w for w in recorded_warnings if issubclass(w.category, DeprecationWarning)
            ]
            self.assertGreaterEqual(len(prop_warnings), 3)

    def test_server_model_deprecation_property_mutation(self):
        srv = ServerModel(
            server_id="test-srv",
            name="Test Server",
            app_id="12345",
            manifest_path="manifest.acf",
        )
        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            srv.current_build = "300"
            srv.latest_build = "400"
            srv.last_status = "Online"

            mutation_warnings = [
                w for w in recorded_warnings if issubclass(w.category, DeprecationWarning)
            ]
            self.assertEqual(len(mutation_warnings), 3)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("ignore")
            self.assertEqual(srv.current_build, "300")
            self.assertEqual(srv.latest_build, "400")
            self.assertEqual(srv.last_status, "Online")

    def test_server_model_dict_clean_of_ephemeral_fields(self):
        srv = ServerModel(
            server_id="test-srv",
            name="Test Server",
            app_id="12345",
            manifest_path="manifest.acf",
        )
        data = srv.model_dump() if hasattr(srv, "model_dump") else srv.dict()
        self.assertNotIn("current_build", data)
        self.assertNotIn("latest_build", data)
        self.assertNotIn("last_status", data)
        self.assertNotIn("_current_build", data)
        self.assertNotIn("_latest_build", data)
        self.assertNotIn("_last_status", data)


class TestWebDTORelocationAndReExports(unittest.TestCase):
    """Verifies web DTOs live in app.web.schemas and can be re-exported via app.core.models with warning."""

    def test_web_dto_classes_in_web_schemas(self):
        self.assertTrue(issubclass(SingleServerSaveRequest, object))
        self.assertTrue(issubclass(SettingsUpdateDTO, object))
        self.assertTrue(issubclass(WebhookPreview, object))

    def test_backward_compatible_forwarding_from_core_models(self):
        import app.core.models as core_models

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            forwarded_save = getattr(core_models, "SingleServerSaveRequest")
            forwarded_dto = getattr(core_models, "SettingsUpdateDTO")
            forwarded_preview = getattr(core_models, "WebhookPreview")

            self.assertIs(forwarded_save, SingleServerSaveRequest)
            self.assertIs(forwarded_dto, SettingsUpdateDTO)
            self.assertIs(forwarded_preview, WebhookPreview)

            deprecation_warnings = [
                w for w in recorded_warnings if issubclass(w.category, DeprecationWarning)
            ]
            self.assertEqual(len(deprecation_warnings), 3)

    def test_core_models_dir_includes_forwarded_dtos(self):
        import app.core.models as core_models

        dir_entries = dir(core_models)
        self.assertIn("SingleServerSaveRequest", dir_entries)
        self.assertIn("SettingsUpdateDTO", dir_entries)
        self.assertIn("WebhookPreview", dir_entries)

    def test_core_models_raises_attribute_error_for_unknown(self):
        import app.core.models as core_models

        with self.assertRaises(AttributeError):
            _ = core_models.NonExistentModel


class TestCleanErrorArchitecture(unittest.TestCase):
    """Verifies domain exception hierarchy and structured error raising without regex scraping."""

    def test_domain_exception_hierarchy(self):
        self.assertTrue(issubclass(ServerNotFoundError, NotFoundError))
        self.assertTrue(issubclass(NotFoundError, DomainError))
        self.assertTrue(issubclass(UnauthorizedError, DomainError))
        self.assertTrue(issubclass(ConflictError, DomainError))
        self.assertTrue(issubclass(ValidationError, DomainError))
        self.assertTrue(issubclass(PterodactylApiError, DomainError))

    def test_operation_result_raises_not_found(self):
        res1 = OperationResult(success=False, error="Target not found", status_code=404)
        with self.assertRaises(NotFoundError):
            res1.raise_if_failed()

        res2 = OperationResult(success=False, error="Server srv-1 not found", error_type="ServerNotFound", status_code=404)
        with self.assertRaises(ServerNotFoundError):
            res2.raise_if_failed(server_id="srv-1")

    def test_operation_result_raises_unauthorized(self):
        res1 = OperationResult(success=False, error="Bad API Key", status_code=401)
        with self.assertRaises(UnauthorizedError):
            res1.raise_if_failed()

        res2 = OperationResult(success=False, error="Forbidden", status_code=403)
        with self.assertRaises(UnauthorizedError):
            res2.raise_if_failed()

    def test_operation_result_raises_conflict(self):
        res = OperationResult(success=False, error="Resource locked", status_code=409)
        with self.assertRaises(ConflictError):
            res.raise_if_failed()

    def test_operation_result_raises_validation_error(self):
        res1 = OperationResult(success=False, error="Invalid field", status_code=422)
        with self.assertRaises(ValidationError):
            res1.raise_if_failed()

        res2 = OperationResult(success=False, error="Validation failed", error_type="ValidationError")
        with self.assertRaises(ValidationError):
            res2.raise_if_failed()

    def test_operation_result_generic_status_code(self):
        res = OperationResult(success=False, error="Server error", status_code=502)
        with self.assertRaises(PterodactylApiError) as ctx:
            res.raise_if_failed()
        self.assertEqual(ctx.exception.status_code, 502)

    def test_local_build_result_structured_raising(self):
        res_401 = LocalBuildResult(build_id=None, error="Unauthorized", status_code=401)
        with self.assertRaises(UnauthorizedError) as ctx:
            res_401.raise_if_failed()
        self.assertEqual(ctx.exception.status_code, 401)

        # Explicit exc_cls override
        with self.assertRaises(ConflictError):
            res_401.raise_if_failed(exc_cls=ConflictError)

        res_404 = LocalBuildResult(build_id=None, error="Manifest missing", status_code=404)
        with self.assertRaises(NotFoundError) as ctx_nf:
            res_404.raise_if_failed()
        self.assertEqual(ctx_nf.exception.status_code, 404)

        with self.assertRaises(ServerNotFoundError) as ctx_snf:
            res_404.raise_if_failed(server_id="srv-1")
        self.assertEqual(ctx_snf.exception.status_code, 404)
        self.assertEqual(ctx_snf.exception.server_id, "srv-1")

        res_409 = LocalBuildResult(build_id=None, error="File locked", status_code=409)
        with self.assertRaises(ConflictError) as ctx_c:
            res_409.raise_if_failed()
        self.assertEqual(ctx_c.exception.status_code, 409)

        res_422 = LocalBuildResult(build_id=None, error="Bad path format", status_code=422)
        with self.assertRaises(ValidationError) as ctx_v:
            res_422.raise_if_failed()
        self.assertEqual(ctx_v.exception.status_code, 422)

        res_500 = LocalBuildResult(build_id=None, error="Server error", status_code=500)
        with self.assertRaises(PterodactylApiError) as ctx_p:
            res_500.raise_if_failed()
        self.assertEqual(ctx_p.exception.status_code, 500)

    def test_server_name_result_structured_raising(self):
        res_401 = ServerNameResult(name=None, error="Invalid API token", status_code=401)
        with self.assertRaises(UnauthorizedError) as ctx:
            res_401.raise_if_failed()
        self.assertEqual(ctx.exception.status_code, 401)

        # Explicit exc_cls override
        with self.assertRaises(ConflictError):
            res_401.raise_if_failed(exc_cls=ConflictError)

        res_404 = ServerNameResult(name=None, error="Panel node missing", status_code=404)
        with self.assertRaises(NotFoundError) as ctx_nf:
            res_404.raise_if_failed()
        self.assertEqual(ctx_nf.exception.status_code, 404)

        with self.assertRaises(ServerNotFoundError) as ctx_snf:
            res_404.raise_if_failed(server_id="srv-test")
        self.assertEqual(ctx_snf.exception.status_code, 404)
        self.assertEqual(ctx_snf.exception.server_id, "srv-test")

        res_502 = ServerNameResult(name=None, error="Bad gateway", status_code=502)
        with self.assertRaises(PterodactylApiError) as ctx_p:
            res_502.raise_if_failed()
        self.assertEqual(ctx_p.exception.status_code, 502)

    def test_no_regex_scraping_from_error_string(self):
        # A result with "Panel HTTP 500" in error string but NO explicit status_code
        # should default to 400 without regex parsing 500 out of the string
        res = OperationResult(success=False, error="Panel HTTP 500: Server exploded")
        with self.assertRaises(PterodactylApiError) as ctx:
            res.raise_if_failed()
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
