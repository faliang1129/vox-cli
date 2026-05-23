"""CLI 主程序 - REPL 循环"""

import getpass
import logging
import os
import sys
from typing import Optional, Sequence

from ..config import ProviderConfig, pai_config
from ..llm.factory import create_from_config, default_base_url_for, default_model_for
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
_SUPPORTED_PROVIDERS = ("glm", "deepseek", "qwen", "ollama")


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
        print("   - Qwen: QWEN_API_KEY + QWEN_MODEL")
        print("   - Ollama: OLLAMA_MODEL + OLLAMA_BASE_URL")
        print("   也可以先运行: vox-code init")
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

    elif cmd == "/init":
        _cmd_init()

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
        selected_model = getattr(new_client, "model_name", model_name or "") or (preset.model if preset else "")
        pai_config.persist_model_selection(provider, selected_model)
        agent.set_llm_client(new_client)
        plan_agent._llm = new_client
        orchestrator._llm = new_client
        presenter._llm = new_client
        model_desc = provider + (f" ({selected_model})" if selected_model else "")
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


def _cmd_init():
    try:
        print()
        print(heading("⚙️ Vox Code 初始化"))
        print(subtle(f"  配置文件: {pai_config.config_file()}"))
        print(subtle("  环境变量仍然优先于 config.json。"))
        print()

        provider = _prompt_provider()
        current = pai_config.providers.get(provider, ProviderConfig())
        default_model = current.model or default_model_for(provider)
        default_base_url = current.base_url or default_base_url_for(provider)
        model = _prompt_text("模型名", default_model, allow_empty=False)
        base_url = _prompt_text("Base URL", default_base_url, allow_empty=False)
        api_key = ""
        if provider != "ollama":
            api_key = _prompt_secret("API Key", current.api_key, required=True)

        provider_config = ProviderConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        pai_config.set_provider_config(provider, provider_config)
        pai_config.persist_model_selection(provider, model)

        print()
        print(f"  {success('✓')} {subtle('配置已保存到: ' + str(pai_config.config_file()))}")
        print(f"  {success('✓')} {subtle('默认模型: ' + provider + ' (' + model + ')')}")
        if provider == "ollama":
            print(subtle("  下一步: 确认本机 Ollama 已启动，然后运行 vox-code"))
        else:
            print(subtle("  下一步: 运行 vox-code"))
    except (EOFError, KeyboardInterrupt):
        print()
        print(subtle("已取消初始化。"))


def _prompt_provider() -> str:
    current = pai_config.default_provider_name
    default_provider = current if current in _SUPPORTED_PROVIDERS else "glm"
    print()
    print("选择模型提供商:")
    for idx, provider in enumerate(_SUPPORTED_PROVIDERS, start=1):
        suffix = " (默认)" if provider == default_provider else ""
        print(f"  {idx}. {_provider_label(provider)}{suffix}")

    while True:
        raw = input(f"提供商 [1-{len(_SUPPORTED_PROVIDERS)} / {default_provider}]: ").strip().lower()
        if not raw:
            return default_provider
        if raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(_SUPPORTED_PROVIDERS):
                return _SUPPORTED_PROVIDERS[index]
        if raw in _SUPPORTED_PROVIDERS:
            return raw
        print("请输入 1/2/3/4 或 provider 名称（glm、deepseek、qwen、ollama）。")


def _prompt_text(label: str, default: str = "", allow_empty: bool = True) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{label}{suffix}: ").strip()
        if raw:
            return raw
        if default:
            return default
        if allow_empty:
            return ""
        print(f"{label} 不能为空。")


def _prompt_secret(label: str, current: str = "", required: bool = False) -> str:
    masked = _mask_secret(current)
    suffix = f" [{masked}]" if masked else ""
    while True:
        raw = getpass.getpass(f"{label}{suffix}: ").strip()
        if raw:
            return raw
        if current:
            return current
        if not required:
            return ""
        print(f"{label} 不能为空。")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _provider_label(provider: str) -> str:
    return {
        "glm": "GLM",
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "ollama": "Ollama",
    }.get(provider, provider.upper())


def _print_cli_usage():
    print("用法:")
    print("  vox-code                启动交互式 REPL")
    print("  vox-code init           初始化模型配置")
    print("  vox-code config-path    显示配置文件路径")
    print("  vox-code --version      显示版本")


def main(argv: Optional[Sequence[str]] = None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        run_repl()
        return

    command = args[0].strip().lower()
    if command in {"-h", "--help", "help"}:
        _print_cli_usage()
        return
    if command in {"-v", "--version", "version"}:
        from .. import __version__
        print(__version__)
        return
    if command == "init":
        _cmd_init()
        return
    if command == "config-path":
        print(pai_config.config_file())
        return

    print(f"未知命令: {args[0]}")
    _print_cli_usage()


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
    print(subtle("  /help 查看可用命令, /init 初始化配置, exit 或 /exit 退出"))
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
