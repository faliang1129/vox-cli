"""CLI 命令解析器 - 解析斜杠命令"""

import shlex
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ParsedCommand:
    command: str
    args: List[str] = field(default_factory=list)
    raw_args: str = ""


class CliCommandParser:
    COMMANDS = {
        "/init": "首次配置模型提供商、API Key 和 URL",
        "/model": "切换 LLM 模型（用法: /model <preset-id|provider[:<model>]>）",
        "/plan": "显示当前执行计划",
        "/team": "切换多 Agent 协作模式",
        "/style": "切换展示模式（work/pet）",
        "/hitl": "设置人工审批模式（auto/always/never）",
        "/policy": "查看或修改安全策略",
        "/audit": "查看审计日志",
        "/index": "索引当前项目代码（供 search_code 检索）",
        "/search": "搜索索引的代码库",
        "/graph": "显示代码关系图",
        "/memory": "查看记忆系统状态",
        "/save": "提取当前会话中的稳定事实并写入长期记忆",
        "/export": "导出当前对话到文件",
        "/clear": "清空当前对话历史（保留系统提示词）",
        "/context": "查看当前上下文统计",
        "/exit": "退出程序",
        "/help": "显示帮助信息",
    }

    @staticmethod
    def parse(line: str) -> Optional[ParsedCommand]:
        stripped = line.strip()
        if not stripped or not stripped.startswith("/"):
            return None

        parts = shlex.split(stripped)
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        return ParsedCommand(command=command, args=args, raw_args=stripped)

    @staticmethod
    def is_command(line: str) -> bool:
        return line.strip().startswith("/")

    @staticmethod
    def print_help():
        print("可用命令:")
        print("  /init                       初始化模型配置")
        print("  /model <preset-id|provider[:<model>]>  切换模型")
        print("  /plan                       查看当前执行计划")
        print("  /team                       切换多 Agent 协作模式")
        print("  /style <work|pet>           切换展示模式")
        print("  /hitl <mode>                设置审批模式 (auto/always/never)")
        print("  /policy                     查看安全策略")
        print("  /audit                      查看审计日志")
        print("  /index                      索引项目代码")
        print("  /search <query>             搜索代码库")
        print("  /graph                      显示代码关系图")
        print("  /memory                     查看记忆状态")
        print("  /save [--global]            保存长期记忆（默认项目级）")
        print("  /export <file>              导出对话到文件")
        print("  /clear                      清空对话历史")
        print("  /context                    查看上下文统计")
        print("  /exit                       退出程序")
        print("  /help                       显示此帮助")
