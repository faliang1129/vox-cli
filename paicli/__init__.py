"""Compatibility shim for the legacy ``voxcli`` package name."""

from importlib import import_module

_voxcli = import_module("voxcli")

__all__ = getattr(_voxcli, "__all__", [])
__file__ = getattr(_voxcli, "__file__", __file__)
__path__ = _voxcli.__path__
__version__ = getattr(_voxcli, "__version__", "")

for _name in __all__:
    globals()[_name] = getattr(_voxcli, _name)
