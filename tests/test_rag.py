"""RAG 模块测试"""
import tempfile
from pathlib import Path
from paicli.rag.chunk import CodeChunk
from paicli.rag.chunker import CodeChunker
from paicli.rag.store import VectorStore


class TestCodeChunk:
    def test_create(self):
        c = CodeChunk(id="c1", file_path="/t.py", content="def f(): pass",
                      language="python", start_line=1, end_line=3)
        assert c.language == "python"
        assert c.id == "c1"


class TestCodeChunker:
    def test_chunk_file_python(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td, "test.py")
            f.write_text("""
def hello():
    print("hello")

class MyClass:
    def method(self):
        pass
""")
            chunker = CodeChunker()
            chunks = chunker.chunk_file(str(f))
            assert len(chunks) > 0
            assert any("hello" in c.content for c in chunks)

    def test_chunk_file_nonexistent(self):
        chunker = CodeChunker()
        chunks = chunker.chunk_file("/nonexistent/file.py")
        assert len(chunks) == 0


class TestVectorStore:
    def setup_method(self):
        self.store = VectorStore(":memory:")

    def test_store_and_count(self):
        assert self.store.chunk_count == 0

    def test_search_by_keyword(self):
        c = CodeChunk(id="c1", file_path="/test.py",
                      content="def hello(): pass",
                      language="python", start_line=1, end_line=1)
        self.store.store_chunk(c)
        results = self.store.search_by_keyword("hello", 5)
        assert len(results) > 0

    def test_remove_file(self):
        c = CodeChunk(id="c2", file_path="/remove.py",
                      content="x=1", language="python",
                      start_line=1, end_line=1)
        self.store.store_chunk(c)
        self.store.remove_file("/remove.py")
        assert self.store.chunk_count == 0

    def test_clear(self):
        c = CodeChunk(id="c3", file_path="/clear.py",
                      content="x=1", language="python",
                      start_line=1, end_line=1)
        self.store.store_chunk(c)
        self.store.clear()
        assert self.store.chunk_count == 0
