"""Tests for recall ranking / formatting and config bounds."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ov_client.client import OVClient
from ov_client.config import PluginConfig
from ov_client.recall import _dedup, _format_find_block, recall_and_format, recall_for_tool
from tests.mock_ov import MockOVServer


def run(coro):
    return asyncio.run(coro)


class TestRecall(unittest.TestCase):
    def setUp(self):
        self.server = MockOVServer()
        self.server.__enter__()
        self.client = OVClient(self.server.url, api_key="test-key", timeout=10)

    def tearDown(self):
        run(self.client.close())
        self.server.__exit__(None, None, None)

    def test_recall_and_format_filters_low_score(self):
        cfg = PluginConfig({"recall_min_score": 0.5, "recall_limit": 8})
        block = run(recall_and_format(self.client, cfg, "我喜欢什么咖啡？", "agent-1"))
        self.assertIsNotNone(block)
        self.assertIn("冰美式", block)
        # low-score (0.3) name entity should be filtered out
        self.assertNotIn("小测", block)

    def test_recall_empty_when_nothing_matches(self):
        cfg = PluginConfig({"recall_min_score": 0.99, "recall_limit": 8})
        block = run(recall_and_format(self.client, cfg, "不存在的话题", "agent-1"))
        self.assertIsNone(block)

    def test_recall_context_mode(self):
        cfg = PluginConfig({"recall_api": "context", "recall_min_score": 0.5})
        block = run(recall_and_format(self.client, cfg, "咖啡", "agent-1"))
        self.assertIsNotNone(block)
        self.assertIn("冰美式", block)

    def test_recall_for_tool_shape(self):
        cfg = PluginConfig({"recall_limit": 5, "recall_min_score": 0})
        result = run(recall_for_tool(self.client, cfg, "咖啡", "agent-1"))
        self.assertIn("query", result)
        self.assertIn("count", result)
        self.assertTrue(result["count"] >= 1)
        self.assertIn("uri", result["results"][0])
        self.assertIn("text", result["results"][0])

    def test_dedup(self):
        items = [
            {"uri": "a", "abstract": "x"},
            {"uri": "a", "abstract": "x"},
            {"uri": "b", "abstract": "y"},
        ]
        out = _dedup(items)
        self.assertEqual(len(out), 2)

    def test_format_block_contains_marker(self):
        cfg = PluginConfig({})
        items = [{"uri": "u1", "abstract": "测试内容", "score": 0.9, "level": 2}]
        block = _format_find_block(items, cfg)
        self.assertIn("<openviking-context>", block)
        self.assertIn("测试内容", block)


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = PluginConfig({})
        self.assertEqual(cfg.recall_mode, "auto")
        self.assertEqual(cfg.recall_api, "find")
        self.assertEqual(cfg.recall_limit, 8)
        self.assertTrue(cfg.scope_isolation)

    def test_bounds(self):
        cfg = PluginConfig({"recall_limit": 9999, "recall_min_score": 5, "commit_message_threshold": -3})
        self.assertEqual(cfg.recall_limit, 30)
        self.assertEqual(cfg.recall_min_score, 1.0)
        self.assertEqual(cfg.commit_message_threshold, 2)

    def test_enum_fallback(self):
        cfg = PluginConfig({"recall_mode": "bogus"})
        self.assertEqual(cfg.recall_mode, "auto")

    def test_base_url_strip(self):
        cfg = PluginConfig({"ov_base_url": "https://x.example.com/"})
        self.assertEqual(cfg.ov_base_url, "https://x.example.com")


if __name__ == "__main__":
    unittest.main()
