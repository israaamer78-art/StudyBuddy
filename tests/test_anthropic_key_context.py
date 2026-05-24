import unittest

import model_config


class ProviderKeyContextTests(unittest.TestCase):
    def test_anthropic_api_key_context_is_set_and_reset(self):
        token = model_config.set_current_api_key("sk-ant-test")
        try:
            self.assertEqual(model_config.current_api_key(), "sk-ant-test")
        finally:
            model_config.reset_current_api_key(token)
        self.assertIsNone(model_config.current_api_key())

    def test_openai_api_key_context_is_set_and_reset(self):
        tokens = model_config.set_current_provider_model("openai", "gpt-5.4-mini")
        token = model_config.set_current_api_key("sk-openai-test")
        try:
            self.assertEqual(model_config.current_provider(), "openai")
            self.assertEqual(model_config.current_model(), "gpt-5.4-mini")
            self.assertEqual(model_config.current_api_key(), "sk-openai-test")
        finally:
            model_config.reset_current_api_key(token)
            model_config.reset_current_provider_model(tokens)
        self.assertIsNone(model_config.current_api_key())
        self.assertEqual(model_config.current_provider(), "anthropic")

    def test_blank_or_invalid_api_key_is_not_used(self):
        token = model_config.set_current_api_key("not-a-key")
        try:
            self.assertIsNone(model_config.current_api_key())
        finally:
            model_config.reset_current_api_key(token)

    def test_provider_model_pair_falls_back_to_provider_default(self):
        provider, model = model_config.normalize_provider_model("openai", "claude-sonnet-4-6")
        self.assertEqual(provider, "openai")
        self.assertEqual(model, "gpt-5.4-mini")


if __name__ == "__main__":
    unittest.main()
