"""macOS-native window tuning for the desktop pet UI.

Qt's `WindowStaysOnTopHint` is not enough on macOS for "desktop pet" behavior.
Tool windows are often backed by `NSPanel`, which may hide when the app loses
focus and will not automatically join every Space or appear over fullscreen
apps. This module applies a narrow set of native tweaks when running on macOS.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import c_bool, c_char_p, c_int, c_long, c_ulong, c_void_p

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"

NSWINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES = 1 << 0
NSWINDOW_COLLECTION_BEHAVIOR_STATIONARY = 1 << 4
NSWINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY = 1 << 8

_FLOATING_WINDOW_LEVEL_KEY = 5
_STATUS_WINDOW_LEVEL_KEY = 9
_FLOATING_WINDOW_LEVEL_FALLBACK = 3
_STATUS_WINDOW_LEVEL_FALLBACK = 25
_NSAPPLICATION_ACTIVATION_POLICY_REGULAR = 0
_NSAPPLICATION_ACTIVATION_POLICY_ACCESSORY = 1

_SEL_CACHE: dict[str, c_void_p] = {}
_LIBOBJC: ctypes.CDLL | None = None
_CORE_GRAPHICS: ctypes.CDLL | None = None


def desired_collection_behavior() -> int:
    return (
        NSWINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
        | NSWINDOW_COLLECTION_BEHAVIOR_STATIONARY
        | NSWINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
    )


def window_level_key_for_role(role: str) -> int:
    if role in {"pet", "overlay"}:
        return _STATUS_WINDOW_LEVEL_KEY
    return _FLOATING_WINDOW_LEVEL_KEY


def tune_window_for_desktop_pet(widget, role: str = "panel") -> bool:
    if not IS_MACOS:
        return False

    ns_window = _resolve_ns_window(widget)
    if not ns_window:
        return False

    try:
        # `setCollectionBehavior:` is fragile across NSWindow/NSPanel variants
        # under Qt on macOS and can raise an uncaught NSException. Keep it
        # opt-in until we have a safer native integration path.
        if _collection_behavior_opt_in_enabled():
            _apply_collection_behavior(ns_window)
        _apply_window_level(ns_window, role)
        _disable_hide_on_deactivate(ns_window)
        _send_void(ns_window, "orderFrontRegardless")
        return True
    except Exception:
        logger.debug("Failed to tune macOS window for role=%s", role, exc_info=True)
        return False


def configure_app_for_desktop_pet() -> bool:
    if not IS_MACOS or _show_dock_icon_opt_in_enabled():
        return False

    try:
        ns_app_class = _objc_get_class("NSApplication")
        if not ns_app_class:
            return False
        ns_app = _send_id(ns_app_class, "sharedApplication")
        if not ns_app:
            return False
        return _send_bool_long(
            ns_app,
            "setActivationPolicy:",
            _NSAPPLICATION_ACTIVATION_POLICY_ACCESSORY,
        )
    except Exception:
        logger.debug("Failed to switch app activation policy", exc_info=True)
        return False


def _resolve_ns_window(widget) -> int:
    if widget is None or not hasattr(widget, "winId"):
        return 0
    try:
        ns_view = int(widget.winId())
    except Exception:
        return 0
    if not ns_view:
        return 0
    return _send_id(ns_view, "window")


def _apply_collection_behavior(ns_window: int):
    current = _send_ulong(ns_window, "collectionBehavior")
    target = current | desired_collection_behavior()
    _send_void_ulong(ns_window, "setCollectionBehavior:", target)


def _collection_behavior_opt_in_enabled() -> bool:
    return os.environ.get("VOX_PET_MACOS_SPACES", "").strip().lower() in {"1", "true", "yes"}


def _show_dock_icon_opt_in_enabled() -> bool:
    return os.environ.get("VOX_PET_SHOW_DOCK", "").strip().lower() in {"1", "true", "yes"}


def _apply_window_level(ns_window: int, role: str):
    key = window_level_key_for_role(role)
    _send_void_long(ns_window, "setLevel:", _cg_window_level_for_key(key))


def _disable_hide_on_deactivate(ns_window: int):
    if _responds_to(ns_window, "setHidesOnDeactivate:"):
        _send_void_bool(ns_window, "setHidesOnDeactivate:", False)


def _cg_window_level_for_key(key: int) -> int:
    core_graphics = _load_core_graphics()
    if core_graphics is None:
        return (
            _STATUS_WINDOW_LEVEL_FALLBACK
            if key == _STATUS_WINDOW_LEVEL_KEY
            else _FLOATING_WINDOW_LEVEL_FALLBACK
        )
    func = core_graphics.CGWindowLevelForKey
    func.argtypes = [c_int]
    func.restype = c_int
    return int(func(key))


def _responds_to(receiver: int, selector_name: str) -> bool:
    selector = _selector("respondsToSelector:")
    target = _selector(selector_name)
    func = ctypes.CFUNCTYPE(c_bool, c_void_p, c_void_p, c_void_p)(
        ("objc_msgSend", _load_libobjc())
    )
    return bool(func(c_void_p(receiver), selector, target))


def _send_id(receiver: int, selector_name: str) -> int:
    func = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p)(("objc_msgSend", _load_libobjc()))
    result = func(c_void_p(receiver), _selector(selector_name))
    return int(result) if result else 0


def _send_bool_long(receiver: int, selector_name: str, value: int) -> bool:
    func = ctypes.CFUNCTYPE(c_bool, c_void_p, c_void_p, c_long)(("objc_msgSend", _load_libobjc()))
    return bool(func(c_void_p(receiver), _selector(selector_name), int(value)))


def _send_ulong(receiver: int, selector_name: str) -> int:
    func = ctypes.CFUNCTYPE(c_ulong, c_void_p, c_void_p)(("objc_msgSend", _load_libobjc()))
    return int(func(c_void_p(receiver), _selector(selector_name)))


def _send_void(receiver: int, selector_name: str):
    func = ctypes.CFUNCTYPE(None, c_void_p, c_void_p)(("objc_msgSend", _load_libobjc()))
    func(c_void_p(receiver), _selector(selector_name))


def _send_void_bool(receiver: int, selector_name: str, value: bool):
    func = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_bool)(("objc_msgSend", _load_libobjc()))
    func(c_void_p(receiver), _selector(selector_name), bool(value))


def _send_void_long(receiver: int, selector_name: str, value: int):
    func = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_long)(("objc_msgSend", _load_libobjc()))
    func(c_void_p(receiver), _selector(selector_name), int(value))


def _send_void_ulong(receiver: int, selector_name: str, value: int):
    func = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_ulong)(("objc_msgSend", _load_libobjc()))
    func(c_void_p(receiver), _selector(selector_name), int(value))


def _selector(name: str) -> c_void_p:
    cached = _SEL_CACHE.get(name)
    if cached is not None:
        return cached
    libobjc = _load_libobjc()
    func = libobjc.sel_registerName
    func.argtypes = [c_char_p]
    func.restype = c_void_p
    selector = func(name.encode("utf-8"))
    _SEL_CACHE[name] = selector
    return selector


def _objc_get_class(name: str) -> int:
    func = _load_libobjc().objc_getClass
    func.argtypes = [c_char_p]
    func.restype = c_void_p
    result = func(name.encode("utf-8"))
    return int(result) if result else 0


def _load_libobjc() -> ctypes.CDLL:
    global _LIBOBJC
    if _LIBOBJC is None:
        _LIBOBJC = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    return _LIBOBJC


def _load_core_graphics() -> ctypes.CDLL | None:
    global _CORE_GRAPHICS
    if _CORE_GRAPHICS is not None:
        return _CORE_GRAPHICS
    try:
        _CORE_GRAPHICS = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
    except OSError:
        _CORE_GRAPHICS = None
    return _CORE_GRAPHICS
