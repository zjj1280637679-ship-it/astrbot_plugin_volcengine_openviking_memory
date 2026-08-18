"""Tests for recall ranking / formatting and config bounds."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ov_client.client import OVClient
from ov_client.config import PluginConfig, access_allowed
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

    def test_recall_filters_structural_files(self):
        # .abstract.md (score 0.8) must be filtered even though it passes the threshold
        cfg = PluginConfig({"recall_min_score": 0.3, "recall_limit": 8})
        block = run(recall_and_format(self.client, cfg, "知识库", "agent-1"))
        self.assertIsNotNone(block)
        self.assertNotIn("本知识库当前未存储独立文件", block)
        self.assertNotIn(".abstract.md", block)

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

    def test_access_switch_defaults(self):
        cfg = PluginConfig({})
        self.assertEqual(cfg.capture_access, "free")
        self.assertEqual(cfg.recall_access, "free")
        self.assertEqual(cfg.tool_access, "free")
        self.assertEqual(cfg.command_access, "free")
        self.assertEqual(cfg.delete_access, "admin")  # destructive default: admin
        self.assertEqual(cfg.tool_io_access, "free")

    def test_access_switch_parse(self):
        cfg = PluginConfig(
            {"capture_access": "admin", "recall_access": "off", "tool_access": "bogus",
             "delete_access": "free", "tool_io_access": "admin"}
        )
        self.assertEqual(cfg.capture_access, "admin")
        self.assertEqual(cfg.recall_access, "off")
        self.assertEqual(cfg.tool_access, "free")  # invalid falls back
        self.assertEqual(cfg.delete_access, "free")
        self.assertEqual(cfg.tool_io_access, "admin")

    def test_tool_io_backcompat(self):
        # legacy capture_tool_io=false means off, absent means free
        self.assertEqual(PluginConfig({"capture_tool_io": False}).tool_io_access, "off")
        self.assertEqual(PluginConfig({"capture_tool_io": True}).tool_io_access, "free")

    def test_knowledge_base_mode(self):
        self.assertFalse(PluginConfig({}).knowledge_base_mode)
        cfg = PluginConfig({"knowledge_base_mode": True})
        self.assertTrue(cfg.knowledge_base_mode)
        self.assertEqual(cfg.knowledge_root, "viking://resources/kb")
        # KB mode scopes recall to the knowledge root by default
        self.assertEqual(cfg.effective_recall_target, "viking://resources/kb")
        # explicit recall_target_uri wins over KB root
        cfg2 = PluginConfig({"knowledge_base_mode": True, "recall_target_uri": "viking://resources/all"})
        self.assertEqual(cfg2.effective_recall_target, "viking://resources/all")
        # non-KB mode with no explicit target -> empty (global recall)
        self.assertEqual(PluginConfig({}).effective_recall_target, "")
        # custom knowledge_root
        cfg3 = PluginConfig({"knowledge_base_mode": True, "knowledge_root": "viking://resources/docs/"})
        self.assertEqual(cfg3.knowledge_root, "viking://resources/docs")

    def test_access_allowed_logic(self):
        # free: everyone
        self.assertTrue(access_allowed("free", False))
        self.assertTrue(access_allowed("free", True))
        # admin: only admins
        self.assertTrue(access_allowed("admin", True))
        self.assertFalse(access_allowed("admin", False))
        # off: nobody
        self.assertFalse(access_allowed("off", True))
        self.assertFalse(access_allowed("off", False))
        # invalid input behaves like free
        self.assertTrue(access_allowed("", False))


if __name__ == "__main__":
    unittest.main()
