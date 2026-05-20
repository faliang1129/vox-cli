"""代码分析器 - 分析代码结构和关系"""

import ast
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from .relation import CodeRelation

logger = logging.getLogger(__name__)


class CodeAnalyzer:
    def __init__(self, project_path: str):
        self._project_path = Path(project_path)

    def analyze_file(self, file_path: str) -> List[CodeRelation]:
        path = Path(file_path)
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return []

        ext = path.suffix.lower()
        if ext == ".py":
            return self._analyze_python(file_path, content)
        elif ext == ".java":
            return self._analyze_java(file_path, content)
        return []

    def _analyze_python(self, file_path: str, content: str) -> List[CodeRelation]:
        relations = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = self._resolve_module(alias.name)
                        if target:
                            relations.append(CodeRelation(
                                source_file=file_path,
                                target_file=target,
                                relation_type="import",
                            ))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            target = self._resolve_module(f"{node.module}.{alias.name}")
                            if target:
                                relations.append(CodeRelation(
                                    source_file=file_path,
                                    target_file=target,
                                    relation_type="import",
                                ))
        except SyntaxError:
            pass
        return relations

    def _analyze_java(self, file_path: str, content: str) -> List[CodeRelation]:
        relations = []
        import_pattern = re.compile(r"^import\s+(?:static\s+)?([\w.]+);", re.MULTILINE)
        for match in import_pattern.finditer(content):
            import_path = match.group(1)
            target = self._resolve_java_class(import_path)
            if target:
                relations.append(CodeRelation(
                    source_file=file_path,
                    target_file=str(target),
                    relation_type="import",
                ))
        return relations

    def _resolve_module(self, module_name: str) -> Optional[str]:
        path = self._project_path / (module_name.replace(".", "/") + ".py")
        if path.exists():
            return str(path)
        init_path = path.parent / "__init__.py"
        if init_path.exists():
            return str(init_path)
        return None

    def _resolve_java_class(self, class_name: str) -> Optional[Path]:
        rel_path = class_name.replace(".", "/") + ".java"
        candidates = list(self._project_path.rglob(rel_path))
        return candidates[0] if candidates else None
