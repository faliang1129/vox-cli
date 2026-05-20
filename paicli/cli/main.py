"""CLI 主程序 - REPL 循环"""

import logging
import os
import sys
from typing import Optional

from ..config import pai_config
from ..llm.factory import create_from_config
from ..agent import Agent, PlanExecuteAgent, AgentOrchestrator
from ..agent.plan_execute_agent import PlanReviewHandler, PlanReviewDecision, PlanReviewAction
from ..tool import ToolRegistry
from ..memory.manager import MemoryManager
from ..hitl import TerminalHitlHandler, HitlToolRegistry, ApprovalPolicy
from ..util.ansi import heading, section, subtle, emphasis
from .parser import CliCommandParser, ParsedCommand

logger = logging.getLogger(__name__)


def _init_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run_repl():
    debug = os.environ.get("VOX_CODE_DEBUG", "").lower() in ("1", "true", "yes")
    _init_logging(debug)

    print(heading("🤖 Vox Code v2.0.0 - Web-aware Tool CLI"))
    print(subtle("输入 /help 查看可用命令，输入 exit 或 /exit 退出\n"))

    llm_client = create_from_config()
    if llm_client is None:
        print("❌ 无法创建 LLM 客户端。请检查环境变量配置。")
        print("   至少需要配置一个模型提供商:")
        print("   - GLM:  GLM_API_KEY + GLM_MODEL")
        print("   - DeepSeek: DEEPSEEK_API_KEY + DEEPSEEK_MODEL")
        print("   - Ollama: OLLAMA_MODEL + OLLAMA_BASE_URL")
        sys.exit(1)

    tool_registry = ToolRegistry()
    memory_manager = MemoryManager(llm_client)

    # 三种运行模式
    mode = "single"  # single, plan, team
    agent = Agent(llm_client, tool_registry)
    plan_agent = PlanExecuteAgent(llm_client, tool_registry, None, memory_manager, None)
    orchestrator = AgentOrchestrator(llm_client, tool_registry, memory_manager)

    terminal_hitl = TerminalHitlHandler()
    hitl_registry = HitlToolRegistry(tool_registry)
    approval_policy = ApprovalPolicy()
    parser = CliCommandParser()

    print(subtle(f"当前模型: {llm_client.__class__.__name__}"))
    print(subtle(f"运行模式: {'单 Agent' if mode == 'single' else 'Plan-and-Execute' if mode == 'plan' else '多 Agent 团队'}"))
    print()

    while True:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + subtle("再见！"))
            break

        if not line:
            continue

        # Handle commands
        parsed = parser.parse(line)
        if parsed:
            _handle_command(parsed, agent, plan_agent, orchestrator, memory_manager,
                            tool_registry, hitl_registry, approval_policy, terminal_hitl,
                            llm_client, lambda: mode, lambda m: set_mode(m))
            continue

        # Handle normal input
        try:
            if mode == "single":
                result = agent.run(line)
                if result:
                    print(result)
            elif mode == "plan":
                result = plan_agent.run(line)
                if result:
                    print(result)
            else:
                result = orchestrator.run(line)
                if result:
                    print(result)
        except Exception as e:
            logger.error("Execution failed", exc_info=True)
            print(f"❌ 执行失败: {e}")


def _handle_command(parsed: ParsedCommand, agent, plan_agent, orchestrator,
                    memory_manager, tool_registry, hitl_registry, approval_policy,
                    terminal_hitl, llm_client, get_mode, set_mode):
    cmd = parsed.command

    if cmd == "/exit":
        print(subtle("再见！"))
        sys.exit(0)

    elif cmd == "/help":
        CliCommandParser.print_help()

    elif cmd == "/model":
        _cmd_model(parsed, agent, plan_agent, orchestrator, llm_client)

    elif cmd == "/plan":
        print(heading("📋 当前执行计划"))
        print("Plan-and-Execute 模式会在每次任务前自动生成计划。")
        print("使用 /team 切换到多 Agent 团队模式，或保持默认的单 Agent 模式。")

    elif cmd == "/team":
        current = get_mode()
        modes = ["single", "plan", "team"]
        idx = modes.index(current) if current in modes else 0
        next_mode = modes[(idx + 1) % len(modes)]
        set_mode(next_mode)
        print(f"切换到 {'单 Agent' if next_mode == 'single' else 'Plan-and-Execute' if next_mode == 'plan' else '多 Agent 团队'} 模式")

    elif cmd == "/hitl":
        if parsed.args:
            mode = parsed.args[0].lower()
            if mode in ("auto", "always", "never"):
                approval_policy.set_mode(mode)
                print(f"审批模式已设置为: {mode}")
            else:
                print("无效模式，可选: auto, always, never")
        else:
            print(f"当前审批模式: {approval_policy.mode}")

    elif cmd == "/policy":
        print(heading("🛡️ 安全策略"))
        print(f"  项目根目录: {tool_registry.project_path}")
        print(f"  审批模式: {approval_policy.mode}")
        print("  PathGuard: 路径限制在项目根目录之内")
        print("  CommandGuard: 禁止危险命令")
        print("  审计日志: ~/.vox-code/audit/")

    elif cmd == "/audit":
        _cmd_audit(tool_registry)

    elif cmd == "/index":
        _cmd_index(parsed, tool_registry)

    elif cmd == "/search":
        _cmd_search(parsed, tool_registry)

    elif cmd == "/memory":
        print(memory_manager.status_summary())

    elif cmd == "/clear":
        agent.clear_history()
        print("对话历史已清空")

    elif cmd == "/context":
        print(agent.get_context_status())

    elif cmd == "/save":
        _cmd_save(parsed, agent)

    else:
        print(f"未知命令: {cmd}，输入 /help 查看可用命令")


def _cmd_model(parsed, agent, plan_agent, orchestrator, llm_client):
    from ..llm.factory import create
    provider = parsed.args[0] if parsed.args else ""
    if not provider:
        print("用法: /model <provider>[:<model>]")
        return

    model_name = None
    if ":" in provider:
        provider, model_name = provider.split(":", 1)

    try:
        new_client = create(provider, model_name)
        agent.set_llm_client(new_client)
        plan_agent._llm = new_client
        orchestrator._llm = new_client
        print(f"已切换到模型: {provider}" + (f" ({model_name})" if model_name else ""))
    except Exception as e:
        print(f"切换模型失败: {e}")


def _cmd_audit(tool_registry):
    log = tool_registry.audit_log
    entries = log.recent(10)
    if not entries:
        print("暂无审计记录")
        return
    print(heading("📋 最近审计记录"))
    for entry in entries:
        icon = {"allow": "✅", "deny": "🛡️", "error": "❌"}.get(entry.outcome, "❓")
        print(f"  {icon} {entry.tool} ({entry.outcome}) - {entry.reason or '无原因'}")


def _cmd_index(parsed, tool_registry):
    project_path = tool_registry.project_path
    print(f"正在索引项目: {project_path}")
    try:
        from ..rag.index import CodeIndex
        indexer = CodeIndex(project_path)
        count = indexer.index_project()
        print(f"索引完成，共 {count} 个代码块")
    except ImportError:
        print("索引功能不可用（缺少 RAG 模块依赖）")
    except Exception as e:
        print(f"索引失败: {e}")


def _cmd_search(parsed, tool_registry):
    query = " ".join(parsed.args) if parsed.args else ""
    if not query:
        print("用法: /search <query>")
        return
    try:
        result = tool_registry._search_code(query, 5)
        print(result)
    except Exception as e:
        print(f"搜索失败: {e}")


def _cmd_save(parsed, agent):
    filename = " ".join(parsed.args) if parsed.args else "conversation.md"
    try:
        history = agent.conversation_history
        lines = []
        for msg in history:
            role = msg.role.upper()
            content = msg.content or ""
            lines.append(f"## {role}\n{content}\n")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"对话已保存到: {filename}")
    except Exception as e:
        print(f"保存失败: {e}")


def main():
    run_repl()


if __name__ == "__main__":
    main()
