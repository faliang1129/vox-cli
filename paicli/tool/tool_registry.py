"""工具注册表 - 管理所有可用工具"""

import json
import subprocess
import time
import logging
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from ..policy.path_guard import PathGuard
from ..policy.command_guard import CommandGuard
from ..policy.exception import PolicyException
from ..policy.audit_log import AuditLog

logger = logging.getLogger(__name__)

_DEFAULT_COMMAND_TIMEOUT = 60
_DEFAULT_BATCH_TIMEOUT = 90
_MAX_PARALLEL_TOOLS = 4
_MAX_COMMAND_OUTPUT_CHARS = 8_000
_MAX_WRITE_FILE_BYTES = 5 * 1024 * 1024
_DEFAULT_FETCH_MAX_CHARS = 8_000
_AUDIT_TOOLS = {"write_file", "execute_command", "create_project"}

ToolExecutor = Callable[[Dict[str, str]], str]


class ToolDef:
    def __init__(self, name: str, description: str, parameters: dict, executor: ToolExecutor):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.executor = executor


class ToolInvocation:
    def __init__(self, id: str, name: str, arguments_json: str):
        self.id = id
        self.name = name
        self.arguments_json = arguments_json


class ToolExecutionResult:
    def __init__(self, id: str, name: str, arguments_json: str,
                 result: str, elapsed_ms: float, timed_out: bool = False):
        self.id = id
        self.name = name
        self.arguments_json = arguments_json
        self.result = result
        self.elapsed_ms = elapsed_ms
        self.timed_out = timed_out

    @staticmethod
    def completed(invocation: ToolInvocation, result: str, elapsed_ms: float) -> "ToolExecutionResult":
        return ToolExecutionResult(invocation.id, invocation.name, invocation.arguments_json,
                                   result, elapsed_ms, False)

    @staticmethod
    def failed(invocation: ToolInvocation, message: str) -> "ToolExecutionResult":
        return ToolExecutionResult.completed(invocation, f"工具执行失败: {message}", 0)

    @staticmethod
    def timed_out(invocation: ToolInvocation, timeout_seconds: int) -> "ToolExecutionResult":
        return ToolExecutionResult(
            invocation.id, invocation.name, invocation.arguments_json,
            f"工具执行超时（{timeout_seconds}秒），已取消",
            timeout_seconds * 1000, True
        )


class ToolRegistry:
    def __init__(self, command_timeout: int = _DEFAULT_COMMAND_TIMEOUT,
                 batch_timeout: int = _DEFAULT_BATCH_TIMEOUT):
        self._tools: Dict[str, ToolDef] = {}
        self._command_timeout = command_timeout
        self._batch_timeout = batch_timeout
        self._project_path: str = Path.cwd().as_posix()
        self._path_guard = PathGuard(self._project_path)
        self._audit_log = AuditLog()
        self._search_provider = None
        self._web_fetcher = None
        self._html_extractor = None
        self._network_policy = None
        self._register_all()

    def _register_all(self):
        self._register_file_tools()
        self._register_shell_tools()
        self._register_code_tools()
        self._register_rag_tools()
        self._register_web_tools()

    def set_project_path(self, project_path: str):
        self._project_path = project_path
        self._path_guard = PathGuard(project_path)

    @property
    def project_path(self) -> str:
        return self._project_path

    @property
    def audit_log(self) -> AuditLog:
        return self._audit_log

    def get_tool_definitions(self) -> List[ToolDef]:
        return list(self._tools.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def execute_tool(self, name: str, arguments_json: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"未知工具: {name}"

        should_audit = name in _AUDIT_TOOLS
        start = time.time()

        try:
            args = json.loads(arguments_json)
            arg_map = {k: str(v) for k, v in args.items()}
            result = tool.executor(arg_map)
            if should_audit:
                self._audit_log.record(AuditLog.allow(name, arguments_json,
                                                       _elapsed_ms(start)))
            return result
        except PolicyException as e:
            if should_audit:
                self._audit_log.record(AuditLog.deny_by_policy(
                    name, arguments_json, str(e), _elapsed_ms(start)))
            return f"🛡️ 策略拒绝: {e}"
        except Exception as e:
            if should_audit:
                self._audit_log.record(AuditLog.error(
                    name, arguments_json, str(e), _elapsed_ms(start)))
            return f"工具执行失败: {e}"

    def execute_tools(self, invocations: List[ToolInvocation]) -> List[ToolExecutionResult]:
        if not invocations:
            return []
        if len(invocations) == 1:
            inv = invocations[0]
            start = time.time()
            result = self.execute_tool(inv.name, inv.arguments_json)
            return [ToolExecutionResult.completed(inv, result, _elapsed_ms(start))]

        parallelism = min(len(invocations), _MAX_PARALLEL_TOOLS)
        results: List[Optional[ToolExecutionResult]] = [None] * len(invocations)

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            future_map: Dict[Future, int] = {}
            for i, inv in enumerate(invocations):
                future = executor.submit(self._execute_single, inv)
                future_map[future] = i

            for future in future_map:
                idx = future_map[future]
                try:
                    results[idx] = future.result(timeout=self._batch_timeout)
                except TimeoutError:
                    results[idx] = ToolExecutionResult.timed_out(
                        invocations[idx], self._batch_timeout)
                except Exception as e:
                    results[idx] = ToolExecutionResult.failed(invocations[idx], str(e))

        return [r for r in results if r is not None]

    def _execute_single(self, inv: ToolInvocation) -> ToolExecutionResult:
        start = time.time()
        result = self.execute_tool(inv.name, inv.arguments_json)
        return ToolExecutionResult.completed(inv, result, _elapsed_ms(start))

    # ---- Tool registration ----

    def _register_file_tools(self):
        self._tools["read_file"] = ToolDef(
            name="read_file",
            description="读取文件内容（仅限项目根目录之内）",
            parameters=_make_params({"path": {"type": "string", "description": "文件路径"}}, ["path"]),
            executor=lambda args: self._read_file(args.get("path", "")),
        )
        self._tools["write_file"] = ToolDef(
            name="write_file",
            description="写入文件内容（仅限项目根目录之内，单文件 5MB 上限）",
            parameters=_make_params({
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            }, ["path", "content"]),
            executor=lambda args: self._write_file(args.get("path", ""), args.get("content", "")),
        )
        self._tools["list_dir"] = ToolDef(
            name="list_dir",
            description="列出目录内容（仅限项目根目录之内）",
            parameters=_make_params({"path": {"type": "string", "description": "目录路径"}}, ["path"]),
            executor=lambda args: self._list_dir(args.get("path", "")),
        )

    def _register_shell_tools(self):
        self._tools["execute_command"] = ToolDef(
            name="execute_command",
            description="在当前项目目录中执行短时 Shell 命令（默认 60 秒超时，不允许全盘扫描）",
            parameters=_make_params({"command": {"type": "string", "description": "要执行的命令"}}, ["command"]),
            executor=lambda args: self._execute_command(args.get("command", "")),
        )

    def _register_code_tools(self):
        self._tools["create_project"] = ToolDef(
            name="create_project",
            description="创建新项目结构",
            parameters=_make_params({
                "name": {"type": "string", "description": "项目名称"},
                "type": {"type": "string", "description": "项目类型 (java/python/node)"},
            }, ["name", "type"]),
            executor=lambda args: self._create_project(args.get("name", ""), args.get("type", "")),
        )

    def _register_rag_tools(self):
        self._tools["search_code"] = ToolDef(
            name="search_code",
            description="语义检索代码库，根据自然语言描述查找相关代码块",
            parameters=_make_params({
                "query": {"type": "string", "description": "自然语言查询描述"},
                "top_k": {"type": "integer", "description": "返回结果数量（默认5）"},
            }, ["query"]),
            executor=lambda args: self._search_code(args.get("query", ""),
                                                     int(args.get("top_k", "5"))),
        )

    def _register_web_tools(self):
        self._tools["web_search"] = ToolDef(
            name="web_search",
            description="搜索互联网，获取实时信息（最新版本、官方文档、技术资讯等）",
            parameters=_make_params({
                "query": {"type": "string", "description": "搜索关键词"},
                "top_k": {"type": "integer", "description": "返回结果数量（默认5）"},
            }, ["query"]),
            executor=lambda args: self._web_search(args.get("query", ""),
                                                    int(args.get("top_k", "5"))),
        )
        self._tools["web_fetch"] = ToolDef(
            name="web_fetch",
            description="抓取指定 URL，提取正文转 Markdown",
            parameters=_make_params({
                "url": {"type": "string", "description": "完整 URL，需 http 或 https 协议"},
                "max_chars": {"type": "integer", "description": "返回 Markdown 最大字符数（默认 8000）"},
            }, ["url"]),
            executor=lambda args: self._web_fetch(args.get("url", ""),
                                                   int(args.get("max_chars", str(_DEFAULT_FETCH_MAX_CHARS)))),
        )

    # ---- Tool implementations ----

    def _read_file(self, path: str) -> str:
        safe = self._path_guard.resolve_safe(path)
        try:
            content = Path(safe).read_text(encoding="utf-8")
            return f"文件内容:\n{content}"
        except Exception as e:
            return f"读取文件失败: {e}"

    def _write_file(self, path: str, content: str) -> str:
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > _MAX_WRITE_FILE_BYTES:
            raise PolicyException(
                f"写入内容 {len(content_bytes)} 字节超过 {_MAX_WRITE_FILE_BYTES // 1024 // 1024}MB 上限")
        safe = self._path_guard.resolve_safe(path)
        try:
            Path(safe).parent.mkdir(parents=True, exist_ok=True)
            Path(safe).write_text(content, encoding="utf-8")
            return f"文件已写入: {path}"
        except Exception as e:
            return f"写入文件失败: {e}"

    def _list_dir(self, path: str) -> str:
        safe = self._path_guard.resolve_safe(path)
        try:
            entries = list(Path(safe).iterdir())
            if not entries:
                return "目录为空或不存在"
            lines = ["目录内容:"]
            for entry in sorted(entries, key=lambda x: (not x.is_dir(), x.name)):
                prefix = "[D]" if entry.is_dir() else "[F]"
                lines.append(f"{prefix} {entry.name}")
            return "\n".join(lines)
        except Exception as e:
            return f"列出目录失败: {e}"

    def _execute_command(self, command: str) -> str:
        normalized = (command or "").strip()
        if not normalized:
            return "执行命令失败: 命令不能为空"
        deny_reason = CommandGuard.check(normalized)
        if deny_reason:
            raise PolicyException(deny_reason)
        try:
            proc = subprocess.run(
                ["bash", "-c", normalized],
                cwd=self._project_path,
                capture_output=True, text=True,
                timeout=self._command_timeout,
            )
            output = proc.stdout + proc.stderr
            if len(output) > _MAX_COMMAND_OUTPUT_CHARS:
                output = output[:_MAX_COMMAND_OUTPUT_CHARS] + "\n...(输出已截断)"
            return f"命令执行完成 (exit code: {proc.returncode})\n{output}"
        except subprocess.TimeoutExpired:
            return f"命令执行超时（{self._command_timeout}秒），已强制终止"
        except Exception as e:
            return f"执行命令失败: {e}"

    def _create_project(self, name: str, type_: str) -> str:
        safe = self._path_guard.resolve_safe(name)
        try:
            root = Path(safe)
            root.mkdir(parents=True, exist_ok=True)
            if type_ == "java":
                (root / "src" / "main" / "java").mkdir(parents=True)
                (root / "src" / "main" / "resources").mkdir(parents=True)
                (root / "pom.xml").write_text(
                    f'<?xml version="1.0" encoding="UTF-8"?>\n<project>\n'
                    f'    <modelVersion>4.0.0</modelVersion>\n'
                    f'    <groupId>com.example</groupId>\n'
                    f'    <artifactId>{name}</artifactId>\n'
                    f'    <version>1.0</version>\n</project>')
            elif type_ == "python":
                (root / name).mkdir(exist_ok=True)
                (root / "main.py").write_text("# 主程序入口\n")
                (root / "requirements.txt").write_text("# 依赖列表\n")
            elif type_ == "node":
                (root / "package.json").write_text(
                    f'{{"name": "{name}", "version": "1.0.0"}}')
            return f"项目已创建: {name} (类型: {type_})"
        except Exception as e:
            return f"创建项目失败: {e}"

    def _search_code(self, query: str, top_k: int) -> str:
        try:
            from ..rag.retriever import CodeRetriever
            from ..rag.formatter import SearchResultFormatter
            with CodeRetriever(self._project_path) as retriever:
                stats = retriever.get_stats()
                if stats.chunk_count == 0:
                    return "代码库尚未索引，请先使用 /index 命令索引当前项目。"
                results = retriever.hybrid_search(query, top_k)
                if not results:
                    return "未找到与查询相关的代码。"
                return SearchResultFormatter.format_for_tool(query, results)
        except ImportError:
            return "代码检索功能不可用（缺少依赖模块）"
        except Exception as e:
            return f"代码检索失败: {e}"

    def _web_search(self, query: str, top_k: int) -> str:
        if not query:
            return "搜索关键词不能为空"
        try:
            from ..web.factory import SearchProviderFactory
            provider = SearchProviderFactory.create()
            if not provider.is_ready():
                return f"⚠️ {provider.unavailable_hint()}"
            results = provider.search(query, top_k)
            return self._format_search_results(provider.name, query, results)
        except ImportError:
            return "联网搜索功能不可用（缺少 web 模块依赖）"
        except Exception as e:
            return f"搜索失败: {e}"

    @staticmethod
    def _format_search_results(provider_name: str, query: str, results) -> str:
        lines = [f"🔍 [{provider_name}] {query}\n"]
        if not results:
            lines.append("未找到相关结果。")
        else:
            for r in results:
                snippet = (r.snippet[:200] + "...") if len(r.snippet) > 200 else r.snippet
                lines.append(f"{r.position}. {r.title}")
                if snippet:
                    lines.append(f"   {snippet}")
                url_part = f"   🔗 {r.url}"
                if r.source:
                    url_part += f"  ({r.source})"
                lines.append(url_part)
                lines.append("")
        return "\n".join(lines).strip()

    def _web_fetch(self, url: str, max_chars: int) -> str:
        if not url:
            return "URL 不能为空"
        try:
            from ..web.network_policy import NetworkPolicy
            from ..web.fetcher import WebFetcher
            from ..web.extractor import HtmlExtractor

            policy = NetworkPolicy()
            deny = policy.check_url(url)
            if deny:
                return f"❌ 网络访问被拒绝: {deny}"
            rate_reason = policy.acquire()
            if rate_reason:
                return f"❌ {rate_reason}"

            raw = WebFetcher().fetch(url)
            extracted = HtmlExtractor().extract(raw["body"], raw["url"])
            md = extracted["markdown"]
            original_length = len(md)
            truncated = False
            if max_chars > 0 and len(md) > max_chars:
                md = md[:max_chars]
                truncated = True

            lines = [f"🌐 抓取: {raw['url']}"]
            if extracted.get("title"):
                lines.append(f"📄 标题: {extracted['title']}")
            if not md:
                lines.append("\n⚠️ 正文为空，可能是 SPA 或防爬墙（已知边界，不重试）")
            else:
                lines.append(f"📏 正文 {original_length} 字符{'（已截断）' if truncated else ''}")
                lines.append("\n---\n")
                lines.append(md)
            return "\n".join(lines)
        except ImportError:
            return "网页抓取功能不可用（缺少 web 模块依赖）"
        except Exception as e:
            return f"抓取失败: {e}"


def _make_params(properties: dict, required: list) -> dict:
    return {"type": "object", "properties": properties, "required": required}


def _elapsed_ms(start: float) -> float:
    return (time.time() - start) * 1000
