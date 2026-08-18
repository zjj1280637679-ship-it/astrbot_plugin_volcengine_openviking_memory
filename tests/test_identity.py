"""Unit tests for identity derivation."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ov_client.config import PluginConfig
from ov_client.identity import derive_agent_id, derive_session_id, safe_peer_id


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.cfg = PluginConfig({})

    def test_group_agent_id(self):
        aid = derive_agent_id(self.cfg, "aiocqhttp", group_id="123456", sender_id="42")
        self.assertEqual(aid, "astrbot:aiocqhttp:group:123456")

    def test_private_agent_id(self):
        aid = derive_agent_id(self.cfg, "aiocqhttp", group_id="", sender_id="42")
        self.assertEqual(aid, "astrbot:aiocqhttp:user:42")

    def test_no_isolation_shared(self):
        cfg = PluginConfig({"scope_isolation": False})
        a1 = derive_agent_id(cfg, "aiocqhttp", group_id="1", sender_id="2")
        a2 = derive_agent_id(cfg, "aiocqhttp", group_id="3", sender_id="4")
        self.assertEqual(a1, "astrbot")
        self.assertEqual(a2, "astrbot")

    def test_session_id_stable_and_urlsafe(self):
        aid = derive_agent_id(self.cfg, "aiocqhttp", group_id="123", sender_id="")
        s1 = derive_session_id(aid)
        s2 = derive_session_id(aid)
        self.assertEqual(s1, s2)
        self.assertTrue(s1.isascii() and s1.replace("-", "").isalnum())

    def test_safe_peer_id(self):
        self.assertEqual(safe_peer_id("a/b c"), "a_b_c")

    def test_non_ascii_agent_id_is_ascii_safe(self):
        # A CJK account name must never leak into an HTTP header.
        aid = derive_agent_id(self.cfg, "webchat", group_id="", sender_id="codex测试实例")
        self.assertTrue(aid.isascii(), f"agent_id must be ASCII: {aid!r}")
        self.assertNotIn("测", aid)
        # Deterministic: same input -> same id.
        aid2 = derive_agent_id(self.cfg, "webchat", group_id="", sender_id="codex测试实例")
        self.assertEqual(aid, aid2)
        # numeric senders (real WeChat) stay clean
        num = derive_agent_id(self.cfg, "aiocqhttp", group_id="", sender_id="2881797534811672064")
        self.assertEqual(num, "astrbot:aiocqhttp:user:2881797534811672064")

    def test_safe_peer_id_ascii(self):
        self.assertTrue(safe_peer_id("张三").isascii())


if __name__ == "__main__":
    unittest.main()
