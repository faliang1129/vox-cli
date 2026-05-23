"""搜索结果格式化器"""

from typing import List

from .store import SearchResult


class SearchResultFormatter:
    @staticmethod
    def format_for_tool(query: str, results: List[SearchResult]) -> str:
        lines = [f"🔍 代码检索: {query}\n"]
        if not results:
            lines.append("未找到相关结果。")
        else:
            for i, r in enumerate(results, 1):
                chunk = r.chunk
                lines.append(f"{i}. [{chunk.chunk_type}] {chunk.file_path}:{chunk.start_line}-{chunk.end_line}")
                lines.append(f"   语言: {chunk.language} | 相关度: {r.score:.3f}")
                code = chunk.content.strip()
                if len(code) > 500:
                    code = code[:500] + "..."
                lines.append(f"   ```{chunk.language}")
                lines.append(code)
                lines.append("   ```")
                lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def format_for_llm(query: str, results: List[SearchResult]) -> str:
        parts = []
        for r in results:
            chunk = r.chunk
            parts.append(
                f"File: {chunk.file_path}:{chunk.start_line}-{chunk.end_line}\n"
                f"Type: {chunk.chunk_type}\n"
                f"```{chunk.language}\n{chunk.content}\n```"
            )
        if parts:
            return f"Related code for query '{query}':\n\n" + "\n---\n".join(parts)
        return ""
