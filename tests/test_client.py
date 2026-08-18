"""Tests for OVClient against an in-process mock server."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ov_client.client import OVClient, OVError
from tests.mock_ov import MockOVHandler, MockOVServer


def run(coro):
    return asyncio.run(coro)


class TestOVClient(unittest.TestCase):
    def setUp(self):
        self.server = MockOVServer()
        self.server.__enter__()
        self.client = OVClient(self.server.url, api_key="test-key", timeout=10)

    def tearDown(self):
        run(self.client.close())
        self.server.__exit__(None, None, None)

    def test_health(self):
        self.assertTrue(run(self.client.health()))

    def test_session_lifecycle(self):
        # create -> get -> add message -> commit
        created = run(self.client.create_session("sess-abc", "agent-1"))
        self.assertEqual(created.get("session_id"), "sess-abc")

        got = run(self.client.get_session("sess-abc", "agent-1"))
        self.assertEqual(got.get("session_id"), "sess-abc")

        ok = run(
            self.client.add_message(
                "sess-abc",
                {"role": "user", "parts": [{"type": "text", "text": "你好"}]},
                "agent-1",
            )
        )
        self.assertTrue(ok)
        self.assertEqual(len(MockOVHandler.messages["sess-abc"]), 1)

        committed = run(self.client.commit_session("sess-abc", "agent-1"))
        self.assertEqual(MockOVHandler.committed.get("sess-abc"), 1)
        self.assertIn("status", committed)

    def test_ensure_session_creates_when_missing(self):
        got = run(self.client.ensure_session("sess-new", "agent-2"))
        self.assertEqual(got.get("session_id"), "sess-new")
        self.assertIn("sess-new", MockOVHandler.sessions)

    def test_find(self):
        items = run(self.client.find("咖啡", agent_id="agent-1", limit=5, score_threshold=0))
        self.assertTrue(any("咖啡" in (it.get("abstract") or "") for it in items))
        self.assertTrue(all("uri" in it for it in items))

    def test_bad_key_rejected(self):
        bad = OVClient(self.server.url, api_key="wrong", timeout=10)
        try:
            with self.assertRaises(OVError):
                run(bad.create_session("sess-x", "agent-1"))
        finally:
            run(bad.close())

    def test_search_context_fallback(self):
        MockOVHandler.fail_search_context = True
        try:
            rendered = run(self.client.search_context("咖啡", agent_id="agent-1", max_tokens=2000))
            self.assertIsNone(rendered)  # falls back gracefully
        finally:
            MockOVHandler.fail_search_context = False


if __name__ == "__main__":
    unittest.main()
