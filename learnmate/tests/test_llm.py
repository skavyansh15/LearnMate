import unittest
from unittest import mock

import requests

from helpers import Base, config
import llm
from errors import UserError


def reply(status=200, text=None, body=None):
    r = mock.Mock(status_code=status)
    r.text = text or ""
    r.json.return_value = body or {"choices": [{"message": {"content": " hello "}}]}
    return r


class LlmTests(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(config, "LLM_API_KEY", "sk-SECRET")
        p.start()
        self.addCleanup(p.stop)

    def test_request_shape_and_result(self):
        with mock.patch("llm.requests.post", return_value=reply()) as post:
            self.assertEqual(llm.complete("sys", "user", 100), "hello")
        args, kw = post.call_args
        self.assertTrue(args[0].endswith("/chat/completions"))
        self.assertEqual(kw["headers"]["Authorization"], "Bearer sk-SECRET")
        self.assertEqual(kw["json"]["max_tokens"], 100)

    def test_identical_requests_are_cached(self):
        with mock.patch("llm.requests.post", return_value=reply()) as post:
            llm.complete("s", "u", 50)
            llm.complete("s", "u", 50)
        self.assertEqual(post.call_count, 1)

    def test_different_base_urls_do_not_collide_cache(self):
        with mock.patch("llm.requests.post", return_value=reply()) as post:
            llm.complete("s", "u", 50, base_url="https://api1.example.com/v1")
            llm.complete("s", "u", 50, base_url="https://api2.example.com/v1")
        self.assertEqual(post.call_count, 2)

    def test_error_never_contains_the_key(self):
        with mock.patch("llm.requests.post", return_value=reply(401, text='bad key sk-SECRET')):
            with self.assertRaises(UserError) as cm:
                llm.complete("s", "u", 50)
        self.assertNotIn("sk-SECRET", cm.exception.message + cm.exception.hint)
        self.assertIn("401", cm.exception.message)

    def test_network_failure_is_friendly(self):
        with mock.patch("llm.requests.post", side_effect=requests.ConnectionError("boom")):
            with self.assertRaises(UserError) as cm:
                llm.complete("s", "u", 50)
        self.assertEqual(cm.exception.code, "ai_unreachable")

    def test_one_retry_on_rate_limit(self):
        with mock.patch("llm.requests.post", side_effect=[reply(429), reply()]) as post, mock.patch("llm.time.sleep"):
            self.assertEqual(llm.complete("s", "u", 50), "hello")
        self.assertEqual(post.call_count, 2)

    def test_empty_answer(self):
        with mock.patch("llm.requests.post", return_value=reply(body={"choices": []})):
            with self.assertRaises(UserError) as cm:
                llm.complete("s", "u", 50)
        self.assertEqual(cm.exception.code, "ai_empty")

    def test_demo_mode_flag_overrides_key(self):
        with mock.patch.object(config, "FORCE_DEMO", True):
            self.assertFalse(llm.is_live())


if __name__ == "__main__":
    unittest.main()
