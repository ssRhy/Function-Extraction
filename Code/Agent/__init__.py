"""Compatibility import namespace for the FunctionExtract-Agent migration.

The implementation lives in ``FunctionExtract_Agent``; this namespace keeps
existing ``Agent.*`` CLI and test imports working without duplicating modules.
"""

import sys
from pathlib import Path

_SOURCE = str(Path(__file__).resolve().parent.parent / "FunctionExtract_Agent")
__path__ = [_SOURCE]
if _SOURCE not in sys.path:
    sys.path.insert(0, _SOURCE)
