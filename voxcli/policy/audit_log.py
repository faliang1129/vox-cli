"""危险工具调用的结构化审计日志（JSONL 格式）"""

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional


_AUDIT_DIR: Optional[Path] = None


def _audit_dir() -> Path:
    global _AUDIT_DIR
    if _AUDIT_DIR is not None:
        return _AUDIT_DIR
    env_dir = os.environ.get("VOX_CODE_AUDIT_DIR", "")
    if env_dir.strip():
        _AUDIT_DIR = Path(env_dir.strip())
    else:
        _AUDIT_DIR = Path.home() / ".vox-code" / "audit"
    return _AUDIT_DIR


def _today_file() -> Path:
    d = date.today().isoformat()
    return _audit_dir() / f"audit-{d}.jsonl"


_MAX_FIELD_CHARS = 1000


def _truncate(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return s if len(s) <= _MAX_FIELD_CHARS else s[:_MAX_FIELD_CHARS] + "...(truncated)"


class AuditEntry:
    def __init__(self, tool: str, args: str, outcome: str,
                 reason: Optional[str] = None, duration_ms: float = 0):
        self.tool = tool
        self.args = args
        self.outcome = outcome
        self.reason = reason
        self.duration_ms = duration_ms


class AuditLog:
    @staticmethod
    def allow(tool: str, args: str, duration_ms: float) -> AuditEntry:
        return AuditEntry(tool, args, "allow", duration_ms=duration_ms)

    @staticmethod
    def deny_by_policy(tool: str, args: str, reason: str, duration_ms: float) -> AuditEntry:
        return AuditEntry(tool, args, "deny", reason=reason, duration_ms=duration_ms)

    @staticmethod
    def error(tool: str, args: str, message: str, duration_ms: float) -> AuditEntry:
        return AuditEntry(tool, args, "error", reason=message, duration_ms=duration_ms)

    def record(self, entry: AuditEntry):
        _write_entry({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "tool": entry.tool,
            "args": _truncate(entry.args),
            "outcome": entry.outcome,
            "reason": entry.reason,
            "approver": "none",
            "durationMs": int(entry.duration_ms),
        })

    @staticmethod
    def recent(n: int = 10) -> list:
        if n <= 0:
            return []
        file_path = _today_file()
        if not file_path.exists():
            return []
        try:
            lines = file_path.read_text(encoding="utf-8").strip().split("\n")
            entries = []
            for raw in lines[-n:]:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    entries.append(AuditEntry(
                        tool=data.get("tool", ""),
                        args=data.get("args", ""),
                        outcome=data.get("outcome", ""),
                        reason=data.get("reason"),
                        duration_ms=data.get("durationMs", 0),
                    ))
                except json.JSONDecodeError:
                    pass
            return entries
        except OSError:
            return []


def _write_entry(entry: dict):
    try:
        log_dir = _audit_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_path = _today_file()
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"⚠️ 审计日志写入失败: {e}")
