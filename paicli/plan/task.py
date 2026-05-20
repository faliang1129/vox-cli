"""任务节点 - 表示一个可执行的任务单元"""

import time
from enum import Enum
from typing import List, Optional, Dict


class TaskType(Enum):
    PLANNING = "PLANNING"
    FILE_READ = "FILE_READ"
    FILE_WRITE = "FILE_WRITE"
    COMMAND = "COMMAND"
    ANALYSIS = "ANALYSIS"
    VERIFICATION = "VERIFICATION"


class TaskStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Task:
    def __init__(self, id: str, description: str, type: TaskType,
                 dependencies: Optional[List[str]] = None):
        self._id = id
        self._description = description
        self._type = type
        self._status = TaskStatus.PENDING
        self._result: Optional[str] = None
        self._error: Optional[str] = None
        self._dependencies: List[str] = dependencies or []
        self._dependents: List[str] = []
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    @property
    def id(self) -> str:
        return self._id

    @property
    def description(self) -> str:
        return self._description

    @property
    def type(self) -> TaskType:
        return self._type

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def result(self) -> Optional[str]:
        return self._result

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def dependencies(self) -> List[str]:
        return list(self._dependencies)

    @property
    def dependents(self) -> List[str]:
        return list(self._dependents)

    @property
    def start_time(self) -> float:
        return self._start_time

    @property
    def end_time(self) -> float:
        return self._end_time

    def add_dependent(self, task_id: str):
        if task_id not in self._dependents:
            self._dependents.append(task_id)

    def add_dependency(self, task_id: str):
        if task_id not in self._dependencies:
            self._dependencies.append(task_id)

    def mark_started(self):
        self._status = TaskStatus.RUNNING
        self._start_time = time.time()

    def mark_completed(self, result: str):
        self._status = TaskStatus.COMPLETED
        self._result = result
        self._end_time = time.time()

    def mark_failed(self, error: str):
        self._status = TaskStatus.FAILED
        self._error = error
        self._end_time = time.time()

    def mark_skipped(self):
        self._status = TaskStatus.SKIPPED
        self._end_time = time.time()

    @property
    def duration(self) -> float:
        if self._start_time == 0:
            return 0.0
        if self._end_time == 0:
            return time.time() - self._start_time
        return self._end_time - self._start_time

    def is_executable(self, all_tasks: Dict[str, "Task"]) -> bool:
        if self._status != TaskStatus.PENDING:
            return False
        for dep_id in self._dependencies:
            dep = all_tasks.get(dep_id)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def __repr__(self) -> str:
        return f"Task[{self._id}: {self._description}] ({self._status.value})"
