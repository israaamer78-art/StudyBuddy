import os
import unittest
from unittest.mock import patch

import app as app_module
from app import app


class SettingsEndpointTests(unittest.TestCase):
    def test_settings_reports_missing_server_anthropic_key_without_exposing_value(self):
        with patch.dict(os.environ, {}, clear=True):
            response = app.test_client().get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"has_server_anthropic_key": False, "has_server_openai_key": False})

    def test_settings_reports_present_server_anthropic_key_without_exposing_value(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secret"}, clear=True):
            response = app.test_client().get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"has_server_anthropic_key": True, "has_server_openai_key": False})

    def test_settings_reports_present_server_openai_key_without_exposing_value(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai-secret"}, clear=True):
            response = app.test_client().get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"has_server_anthropic_key": False, "has_server_openai_key": True})

    def test_validate_key_requires_browser_or_server_key(self):
        with patch.dict(os.environ, {}, clear=True):
            response = app.test_client().post("/api/settings/validate-key", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "missing_key")

    def test_validate_key_returns_provider_result_without_exposing_key(self):
        with patch.object(app_module, "validate_anthropic_key", return_value={"ok": True, "status": "valid", "message": "Anthropic key validated."}):
            response = app.test_client().post("/api/settings/validate-key", json={"anthropic_api_key": "sk-ant-test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "status": "valid", "message": "Anthropic key validated."})

    def test_validate_openai_key_returns_provider_result_without_exposing_key(self):
        with patch.object(app_module, "validate_openai_key", return_value={"ok": True, "status": "valid", "message": "OpenAI key validated."}) as validate:
            response = app.test_client().post(
                "/api/settings/validate-key",
                json={"provider": "openai", "model": "gpt-5.4-mini", "openai_api_key": "sk-openai-test"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "status": "valid", "message": "OpenAI key validated."})
        validate.assert_called_once_with("sk-openai-test", "gpt-5.4-mini")

    def test_openai_validation_treats_probe_output_limit_as_success(self):
        class FakeBadRequest(app_module.openai.BadRequestError):
            def __init__(self):
                Exception.__init__(self)
                self.body = {
                    "error": {
                        "message": "Could not finish the message because max_tokens or model output limit was reached.",
                    }
                }

        with patch("app.OpenAI") as openai_cls:
            openai_cls.return_value.chat.completions.create.side_effect = FakeBadRequest()
            result = app_module.validate_openai_key("sk-openai-test", "gpt-5.4-mini")

        self.assertEqual(result, {"ok": True, "status": "valid", "message": "OpenAI key validated."})


if __name__ == "__main__":
    unittest.main()
