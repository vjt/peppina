"""Import the hOn client as a top-level package: the integration package
itself needs Home Assistant, the client does not."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "peppina"))
