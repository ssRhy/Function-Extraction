"""Load the standalone Story Pattern Agent from its hyphenated directory."""

import importlib.util
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1] / "StoryPattern_Agent"
_NAME = "story_pattern_agent"
_SPEC = importlib.util.spec_from_file_location(
    _NAME, _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)]
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_NAME] = _MODULE
_SPEC.loader.exec_module(_MODULE)

inputs = sys.modules[f"{_NAME}.inputs"]
clusters = sys.modules[f"{_NAME}.clusters"]
summaries = sys.modules[f"{_NAME}.summaries"]
sequences = sys.modules[f"{_NAME}.sequences"]
variants = sys.modules[f"{_NAME}.variants"]
review = sys.modules[f"{_NAME}.review"]
