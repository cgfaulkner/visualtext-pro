"""Test configuration for path setup."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Allow core modules to be imported by name (e.g. pptx_alt_injector from offline_placeholders)
if str(ROOT / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / "core"))
