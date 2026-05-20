"""路径围栏：文件类工具调用的路径合法性检查"""

import os
from pathlib import Path

from .exception import PolicyException


class PathGuard:
    def __init__(self, root: str):
        if not root or not root.strip():
            raise ValueError("项目根路径不能为空")
        candidate = Path(root).resolve()
        self._root_path = candidate

    @property
    def root_path(self) -> Path:
        return self._root_path

    def resolve_safe(self, input_path: str) -> Path:
        if not input_path or not input_path.strip():
            raise PolicyException("路径不能为空")

        raw = Path(input_path)
        resolved = raw if raw.is_absolute() else (self._root_path / raw)
        resolved = resolved.resolve()

        if not str(resolved).startswith(str(self._root_path)):
            raise PolicyException(
                f"路径越界: {input_path} 不在项目根 {self._root_path} 之内"
            )
        return resolved
