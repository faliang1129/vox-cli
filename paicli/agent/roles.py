"""Agent 角色定义与通信消息"""

from enum import Enum
from typing import Optional


class AgentRole(Enum):
    PLANNER = ("规划者", "负责分析用户任务，制定执行计划，将复杂任务拆解为可执行的子任务")
    WORKER = ("执行者", "负责执行具体任务步骤，调用工具完成文件操作、命令执行等操作")
    REVIEWER = ("检查者", "负责检查执行结果的质量和正确性，提供改进建议")

    def __init__(self, display_name: str, description: str):
        self._display_name = display_name
        self._description = description

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def description(self) -> str:
        return self._description


class AgentMessageType(Enum):
    TASK = "TASK"
    RESULT = "RESULT"
    FEEDBACK = "FEEDBACK"
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    ERROR = "ERROR"


class AgentMessage:
    def __init__(self, from_agent: str, from_role: Optional[AgentRole],
                 content: str, type: AgentMessageType):
        self._from_agent = from_agent
        self._from_role = from_role
        self._content = content
        self._type = type

    @property
    def from_agent(self) -> str:
        return self._from_agent

    @property
    def from_role(self) -> Optional[AgentRole]:
        return self._from_role

    @property
    def content(self) -> str:
        return self._content

    @property
    def type(self) -> AgentMessageType:
        return self._type

    @staticmethod
    def task(from_agent: str, content: str) -> "AgentMessage":
        return AgentMessage(from_agent, None, content, AgentMessageType.TASK)

    @staticmethod
    def result(from_agent: str, role: AgentRole, content: str) -> "AgentMessage":
        return AgentMessage(from_agent, role, content, AgentMessageType.RESULT)

    @staticmethod
    def feedback(from_agent: str, content: str) -> "AgentMessage":
        return AgentMessage(from_agent, AgentRole.REVIEWER, content, AgentMessageType.FEEDBACK)

    @staticmethod
    def approval(from_agent: str, content: str) -> "AgentMessage":
        return AgentMessage(from_agent, AgentRole.REVIEWER, content, AgentMessageType.APPROVAL)

    @staticmethod
    def rejection(from_agent: str, content: str) -> "AgentMessage":
        return AgentMessage(from_agent, AgentRole.REVIEWER, content, AgentMessageType.REJECTION)

    @staticmethod
    def error(from_agent: str, role: AgentRole, content: str) -> "AgentMessage":
        return AgentMessage(from_agent, role, content, AgentMessageType.ERROR)
