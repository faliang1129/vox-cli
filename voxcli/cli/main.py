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
from ..prompting import PresentationMode, ResponsePresenter
from ..util.ansi import heading, section, subtle, emphasis, success, error
from ..util.animation import ProgressDots, Typewriter
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

    _animate_startup()

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
    state = {
        "mode": "single",
        "presentation_mode": _default_presentation_mode().value,
    }
    agent = Agent(llm_client, tool_registry)
    plan_agent = PlanExecuteAgent(llm_client, tool_registry, None, memory_manager, None)
    orchestrator = AgentOrchestrator(llm_client, tool_registry, memory_manager)
    presenter = ResponsePresenter(llm_client)

    terminal_hitl = TerminalHitlHandler()
    hitl_registry = HitlToolRegistry(tool_registry)
    approval_policy = ApprovalPolicy()
    parser = CliCommandParser()

    tw = Typewriter()
    tw.write_fast(subtle(f"  Model: {llm_client.__class__.__name__}\n"))
    tw.write_fast(subtle(f"  Mode:  {_render_mode_label(state['mode'])}\n"))
    tw.write_fast(subtle(f"  Style: {state['presentation_mode']}\n"))
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
                            llm_client, presenter, lambda: state["mode"],
                            lambda m: state.__setitem__("mode", m),
                            lambda: state["presentation_mode"],
                            lambda m: state.__setitem__("presentation_mode", m))
            continue

        # Handle normal input
        try:
            mode = state["mode"]
            if mode == "single":
                result = agent.run(line)
                if result:
                    _print_presented_result(presenter, state["presentation_mode"], line, result)
            elif mode == "plan":
                result = plan_agent.run(line)
                if result:
                    _print_presented_result(presenter, state["presentation_mode"], line, result)
            else:
                result = orchestrator.run(line)
                if result:
                    _print_presented_result(presenter, state["presentation_mode"], line, result)
        except Exception as e:
            logger.error("Execution failed", exc_info=True)
            print(f"❌ 执行失败: {e}")


def _handle_command(parsed: ParsedCommand, agent, plan_agent, orchestrator,
                    memory_manager, tool_registry, hitl_registry, approval_policy,
                    terminal_hitl, llm_client, presenter, get_mode, set_mode,
                    get_presentation_mode, set_presentation_mode):
    cmd = parsed.command

    if cmd == "/exit":
        print(subtle("再见！"))
        sys.exit(0)

    elif cmd == "/help":
        CliCommandParser.print_help()

    elif cmd == "/model":
        _cmd_model(parsed, agent, plan_agent, orchestrator, llm_client, presenter)

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
        print(f"  {success('✓')} {subtle(f'Switched to {_render_mode_label(next_mode)} mode')}")

    elif cmd == "/style":
        if parsed.args:
            if not PresentationMode.is_valid(parsed.args[0]):
                print(subtle("  Invalid style, options: work, pet"))
                return
            requested = PresentationMode.normalize(parsed.args[0]).value
            set_presentation_mode(requested)
            print(f"  {success('✓')} {subtle('Style set to: ' + requested)}")
        else:
            print(subtle(f"  Current style: {get_presentation_mode()}"))

    elif cmd == "/hitl":
        if parsed.args:
            mode = parsed.args[0].lower()
            if mode in ("auto", "always", "never"):
                approval_policy.set_mode(mode)
                print(f"  {success('✓')} {subtle('HITL policy set to: ' + mode)}")
            else:
                print(subtle("  Invalid mode, options: auto, always, never"))
        else:
            print(subtle(f"  Current HITL policy: {approval_policy.mode}"))

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


def _cmd_model(parsed, agent, plan_agent, orchestrator, llm_client, presenter):
    from ..llm.factory import create
    target = parsed.args[0] if parsed.args else ""
    if not target:
        print("用法: /model <preset-id|provider[:<model>]>")
        return

    provider, model_name, preset = pai_config.resolve_model_selection(target)

    try:
        new_client = create(provider, model_name)
        if new_client is None:
            print(f"  {error('✗')} {subtle(f'Failed to create client for provider={provider}')}")
            return
        if preset is not None:
            pai_config.set_active_model_preset(preset.id)
        agent.set_llm_client(new_client)
        plan_agent._llm = new_client
        orchestrator._llm = new_client
        presenter._llm = new_client
        model_desc = provider + (f" ({model_name})" if model_name else "")
        print(f"  {success('✓')} {subtle('Model switched to: ' + model_desc)}")
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


def _animate_startup():
    """Claude Code 风格的启动动画"""
    print(heading("╭──────────────────────────────╮"))
    print(heading("│       Vox Code v2.0.0         │"))
    print(heading("│   Web-aware Tool CLI           │"))
    print(heading("╰──────────────────────────────╯"))
    dots = ProgressDots("Initializing")
    dots.start()
    import time
    time.sleep(0.4)
    dots.stop(success("  Ready"))
    print(subtle("  /help 查看可用命令, exit 或 /exit 退出"))
    print()


def _render_mode_label(mode: str) -> str:
    return "单 Agent" if mode == "single" else "Plan-and-Execute" if mode == "plan" else "多 Agent 团队"


def _default_presentation_mode() -> PresentationMode:
    return PresentationMode.normalize(os.environ.get("VOX_CODE_PRESENTATION_MODE", "work"))


def _print_presented_result(presenter: ResponsePresenter, presentation_mode: str,
                            user_input: str, raw_result: str):
    presented = presenter.present(user_input, raw_result, presentation_mode)
    if presented.display_response:
        print(presented.display_response)


if __name__ == "__main__":
    main()
