"""Make the extension-less `mouseferry` script importable as a module."""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "mouseferry"


def _load_mouseferry():
    spec = importlib.util.spec_from_loader(
        "mouseferry_script",
        importlib.machinery.SourceFileLoader("mouseferry_script", str(SCRIPT_PATH)),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mouseferry_script"] = mod
    spec.loader.exec_module(mod)
    return mod


mouseferry = _load_mouseferry()
