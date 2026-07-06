import os
import unittest
from unittest.mock import patch

from llm.local_llm_client import DEFAULT_TIMEOUT_SECONDS, load_config_from_env


class LoadConfigFromEnvTimeoutTests(unittest.TestCase):
    def test_timeout_env_absent_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_valid_positive_int_uses_value(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "120"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(120, config.timeout_seconds)

    def test_timeout_env_empty_string_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": ""}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_invalid_string_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "abc"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_zero_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "0"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_negative_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "-5"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)


if __name__ == "__main__":
    unittest.main()
