"""任务规划模块测试"""
from paicli.plan.task import Task, TaskType, TaskStatus
from paicli.plan.execution_plan import ExecutionPlan


class TestTask:
    def test_create(self):
        t = Task("t1", "读取文件", TaskType.FILE_READ)
        assert t.id == "t1"
        assert t.description == "读取文件"
        assert t.type == TaskType.FILE_READ
        assert t.status == TaskStatus.PENDING

    def test_is_executable_no_deps(self):
        t = Task("t1", "test", TaskType.COMMAND)
        assert t.is_executable({}) is True

    def test_not_executable_with_pending_deps(self):
        t1 = Task("t1", "dep", TaskType.FILE_READ)
        t2 = Task("t2", "test", TaskType.COMMAND)
        t2.add_dependency("t1")
        all_tasks = {"t1": t1, "t2": t2}
        # t2 not executable because t1 is PENDING
        assert t2.is_executable(all_tasks) is False

    def test_executable_when_deps_completed(self):
        t1 = Task("t1", "dep", TaskType.FILE_READ)
        t1.mark_completed("ok")
        t2 = Task("t2", "test", TaskType.COMMAND)
        t2.add_dependency("t1")
        all_tasks = {"t1": t1, "t2": t2}
        assert t2.is_executable(all_tasks) is True

    def test_mark_completed(self):
        t = Task("t1", "test", TaskType.ANALYSIS)
        t.mark_completed("ok")
        assert t.status == TaskStatus.COMPLETED
        assert t.result == "ok"


class TestExecutionPlan:
    def test_add_and_get_task(self):
        plan = ExecutionPlan("p1", "goal")
        t = Task("t1", "desc", TaskType.FILE_READ)
        plan.add_task(t)
        assert plan.get_task("t1") is t
        assert plan.goal == "goal"

    def test_compute_execution_order(self):
        plan = ExecutionPlan("p1", "goal")
        t1 = Task("t1", "step1", TaskType.FILE_READ)
        t2 = Task("t2", "step2", TaskType.FILE_WRITE)
        t2.add_dependency("t1")
        plan.add_task(t1)
        plan.add_task(t2)
        ok = plan.compute_execution_order()
        assert ok is True
        assert plan.get_execution_order() == ["t1", "t2"]

    def test_execution_batches(self):
        plan = ExecutionPlan("p1", "goal")
        t1 = Task("t1", "step1", TaskType.FILE_READ)
        t2 = Task("t2", "step2", TaskType.COMMAND)
        t3 = Task("t3", "step3", TaskType.FILE_WRITE)
        t3.add_dependency("t1")
        plan.add_task(t1)
        plan.add_task(t2)
        plan.add_task(t3)
        plan.compute_execution_order()
        batches = plan.get_execution_batches()
        assert len(batches) == 2
        assert {t.id for t in batches[0]} == {"t1", "t2"}
        assert {t.id for t in batches[1]} == {"t3"}

    def test_detect_cycle(self):
        plan = ExecutionPlan("p1", "cycle")
        t1 = Task("t1", "a", TaskType.ANALYSIS)
        t2 = Task("t2", "b", TaskType.ANALYSIS)
        t1.add_dependency("t2")
        t2.add_dependency("t1")
        plan.add_task(t1)
        plan.add_task(t2)
        ok = plan.compute_execution_order()
        assert ok is False
