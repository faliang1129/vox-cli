"""记忆模块测试"""
from paicli.memory.short_term import ConversationMemory
from paicli.memory.long_term import LongTermMemory
from paicli.memory.entry import MemoryEntry, MemoryType


class TestConversationMemory:
    def test_store_and_size(self):
        m = ConversationMemory()
        e1 = MemoryEntry(id="m1", content="你好", type=MemoryType.FACT)
        e2 = MemoryEntry(id="m2", content="你好！", type=MemoryType.FACT)
        m.store(e1)
        m.store(e2)
        assert m.size() == 2

    def test_status_summary(self):
        m = ConversationMemory()
        e = MemoryEntry(id="m1", content="hi", type=MemoryType.FACT)
        m.store(e)
        summary = m.status_summary()
        assert "token" in summary.lower()

    def test_clear(self):
        m = ConversationMemory()
        e = MemoryEntry(id="m1", content="hi", type=MemoryType.FACT)
        m.store(e)
        m.clear()
        assert m.size() == 0

    def test_token_budget_eviction(self):
        m = ConversationMemory(max_tokens=10)
        e1 = MemoryEntry(id="e1", content="x" * 100, type=MemoryType.FACT, token_count=50)
        e2 = MemoryEntry(id="e2", content="y" * 100, type=MemoryType.FACT, token_count=50)
        m.store(e1)
        m.store(e2)
        # e1 should be evicted when e2 is stored
        assert m.retrieve("e1") is None or m.size() == 1


class TestLongTermMemory:
    def setup_method(self):
        self.m = LongTermMemory()
        self.m.clear()

    def test_store_and_retrieve(self):
        self.m.clear()
        e = MemoryEntry(id="t1", content="user likes Python", type=MemoryType.FACT)
        self.m.store(e)
        assert self.m.size() == 1
        assert self.m.retrieve("t1") is e

    def test_search(self):
        self.m.clear()
        e = MemoryEntry(id="t2", content="user prefers Go", type=MemoryType.FACT)
        self.m.store(e)
        results = self.m.search("Go", 5)
        assert len(results) > 0

    def test_clear(self):
        self.m.clear()
        assert self.m.size() == 0

    def test_delete(self):
        self.m.clear()
        e = MemoryEntry(id="d1", content="delete me", type=MemoryType.FACT)
        self.m.store(e)
        assert self.m.delete("d1") is True
        assert self.m.size() == 0

    def test_dedup(self):
        self.m.clear()
        e1 = MemoryEntry(id="u1", content="unique", type=MemoryType.FACT)
        e2 = MemoryEntry(id="u2", content="unique", type=MemoryType.FACT)
        self.m.store(e1)
        self.m.store(e2)
        assert self.m.size() == 1
        self.m.clear()
