"""Agent 模块测试"""
from paicli.agent.agent_budget import AgentBudget, ExitReason
from paicli.agent.agent import Agent
from paicli.agent.roles import AgentRole, AgentMessage, AgentMessageType
from paicli.agent.plan_execute_agent import PlanExecuteAgent
from paicli.agent.agent_orchestrator import AgentOrchestrator
from paicli.llm.factory import create_from_config
from paicli.tool import ToolRegistry


class TestAgentBudget:
    def test_default_within_budget(self):
        b = AgentBudget()
        assert b.check() == ExitReason.WITHIN_BUDGET

    def test_token_exceeded(self):
        b = AgentBudget(token_budget=100)
        b.record_tokens(99, 2)
        assert b.check() == ExitReason.TOKEN_BUDGET_EXCEEDED

    def test_hard_iteration_limit(self):
        b = AgentBudget(hard_max_iterations=3)
        for _ in range(3):
            b.begin_iteration()
        assert b.check() == ExitReason.HARD_ITERATION_LIMIT

    def test_stagnation_detected(self):
        from paicli.llm.base import ToolCall
        b = AgentBudget(stagnation_window=3)
        tc = [ToolCall(id="c1", name="read_file", arguments="{}")]
        for _ in range(3):
            b.record_tool_calls(tc)
        assert b.check() == ExitReason.STAGNATION_DETECTED

    def test_describe_exit(self):
        b = AgentBudget()
        desc = b.describe_exit(ExitReason.TOKEN_BUDGET_EXCEEDED)
        assert "Token" in desc


class TestAgent:
    def test_create(self):
        client = create_from_config()
        agent = Agent(client)
        assert agent is not None

    def test_clear_history_keeps_system(self):
        client = create_from_config()
        agent = Agent(client)
        agent.clear_history()
        assert len(agent.conversation_history) == 1
        assert agent.conversation_history[0].role == "system"

    def test_context_status(self):
        client = create_from_config()
        agent = Agent(client)
        status = agent.get_context_status()
        assert "system" in status


class TestAgentRoles:
    def test_enum_names(self):
        assert AgentRole.PLANNER.name == "PLANNER"
        assert AgentRole.WORKER.name == "WORKER"
        assert AgentRole.REVIEWER.name == "REVIEWER"

    def test_agent_message_task(self):
        m = AgentMessage.task("planner", "do something")
        assert m.type == AgentMessageType.TASK
        assert m.content == "do something"

    def test_agent_message_result(self):
        m = AgentMessage.result("worker", AgentRole.WORKER, "done")
        assert m.type == AgentMessageType.RESULT
        assert m.from_agent == "worker"


class TestPlanExecuteAgent:
    def test_create(self):
        client = create_from_config()
        agent = PlanExecuteAgent(client, ToolRegistry(), None, None, None)
        assert agent is not None


class TestOrchestrator:
    def test_create(self):
        client = create_from_config()
        orc = AgentOrchestrator(client, ToolRegistry(), None)
        assert orc is not None
