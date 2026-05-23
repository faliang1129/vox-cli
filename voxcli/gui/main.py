"""PySide6 desktop pet entrypoint."""

from __future__ import annotations

import sys


def main():
    try:
        from .pet_app import run_pet_app
    except ImportError as exc:
        print(
            "PySide6 未安装，无法启动桌宠界面。\n"
            "请先安装依赖，例如: pip install PySide6"
        )
        raise SystemExit(1) from exc

    try:
        raise SystemExit(run_pet_app(sys.argv))
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1) from exc
