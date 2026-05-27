"""Background PyPI version checks for the CLI."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from queue import Empty, Queue
import re
import subprocess
import sys
import threading
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_PACKAGE_NAME = "vox-code"
_DEFAULT_TIMEOUT = 2.5
_PYPI_URL_TEMPLATE = "https://pypi.org/pypi/{package}/json"
_VERSION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)(.*)$")


@dataclass(frozen=True)
class UpdateNotice:
    package_name: str
    current_version: str
    latest_version: str

    def render(self) -> str:
        return (
            f"📦 检测到新版本: {self.current_version} -> {self.latest_version}\n"
            f"   运行 `pip install -U {self.package_name}` 升级"
        )


@dataclass(frozen=True)
class UpdateActionResult:
    success: bool
    command: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class AsyncUpdateChecker:
    def __init__(self,
                 current_version: str,
                 package_name: str = _DEFAULT_PACKAGE_NAME,
                 skipped_version: str = "",
                 timeout: float = _DEFAULT_TIMEOUT,
                 get: Optional[Callable[..., httpx.Response]] = None):
        self._current_version = current_version
        self._package_name = package_name
        self._skipped_version = skipped_version
        self._timeout = timeout
        self._get = get or httpx.get
        self._queue: Queue[UpdateNotice] = Queue(maxsize=1)
        self._started = False

    def start(self):
        if self._started or not update_check_enabled():
            return
        self._started = True
        thread = threading.Thread(
            target=self._run,
            name="vox-code-update-check",
            daemon=True,
        )
        thread.start()

    def poll_notice(self) -> UpdateNotice | None:
        try:
            return self._queue.get_nowait()
        except Empty:
            return None

    def _run(self):
        try:
            notice = check_for_update(
                current_version=self._current_version,
                package_name=self._package_name,
                skipped_version=self._skipped_version,
                timeout=self._timeout,
                get=self._get,
            )
            if notice is not None:
                self._queue.put_nowait(notice)
        except Exception:
            logger.debug("Background update check failed", exc_info=True)


def update_check_enabled() -> bool:
    disabled = os.environ.get("VOX_CODE_DISABLE_UPDATE_CHECK", "").strip().lower()
    return disabled not in {"1", "true", "yes"}


def default_timeout() -> float:
    raw = os.environ.get("VOX_CODE_UPDATE_CHECK_TIMEOUT", "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT
    try:
        return max(float(raw), 0.1)
    except ValueError:
        return _DEFAULT_TIMEOUT


def check_for_update(current_version: str,
                     package_name: str = _DEFAULT_PACKAGE_NAME,
                     skipped_version: str = "",
                     timeout: float = _DEFAULT_TIMEOUT,
                     get: Optional[Callable[..., httpx.Response]] = None) -> UpdateNotice | None:
    latest_version = fetch_latest_version(package_name, timeout=timeout, get=get)
    if not latest_version:
        return None
    if skipped_version and latest_version == skipped_version.strip():
        return None
    if not is_newer_version(latest_version, current_version):
        return None
    return UpdateNotice(
        package_name=package_name,
        current_version=current_version,
        latest_version=latest_version,
    )


def run_auto_update(package_name: str = _DEFAULT_PACKAGE_NAME,
                    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None) -> UpdateActionResult:
    command = (sys.executable, "-m", "pip", "install", "-U", package_name)
    executor = runner or subprocess.run
    try:
        completed = executor(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return UpdateActionResult(
            success=False,
            command=command,
            stderr=str(exc),
            returncode=1,
        )
    return UpdateActionResult(
        success=completed.returncode == 0,
        command=command,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        returncode=completed.returncode,
    )


def fetch_latest_version(package_name: str = _DEFAULT_PACKAGE_NAME,
                         timeout: float = _DEFAULT_TIMEOUT,
                         get: Optional[Callable[..., httpx.Response]] = None) -> str | None:
    getter = get or httpx.get
    try:
        response = getter(
            _PYPI_URL_TEMPLATE.format(package=package_name),
            headers={"Accept": "application/json", "User-Agent": f"{package_name}-update-check"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.debug("Failed to fetch latest version from PyPI", exc_info=True)
        return None
    return extract_latest_version(payload)


def extract_latest_version(payload: dict) -> str | None:
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return str(version).strip() if version else None


def is_newer_version(latest_version: str, current_version: str) -> bool:
    latest_release, latest_suffix = _parse_version(latest_version)
    current_release, current_suffix = _parse_version(current_version)
    release_cmp = _compare_release(latest_release, current_release)
    if release_cmp != 0:
        return release_cmp > 0
    if latest_suffix == current_suffix:
        return False
    if not latest_suffix and current_suffix:
        return True
    if latest_suffix and not current_suffix:
        return False
    return latest_suffix > current_suffix


def _parse_version(version: str) -> tuple[tuple[int, ...], str]:
    normalized = (version or "").strip().lower()
    match = _VERSION_RE.match(normalized)
    if not match:
        return (), normalized
    release = tuple(int(part) for part in match.group(1).split("."))
    suffix = match.group(2).strip()
    return release, suffix


def _compare_release(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    size = max(len(left), len(right))
    for idx in range(size):
        lval = left[idx] if idx < len(left) else 0
        rval = right[idx] if idx < len(right) else 0
        if lval > rval:
            return 1
        if lval < rval:
            return -1
    return 0
