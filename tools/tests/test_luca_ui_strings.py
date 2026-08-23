import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
GAME_TOOLS = ROOT / "game-tools"


def load_module(name, path):
    sys.path.insert(0, str(GAME_TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_iter_cstrings_keeps_utf8_and_embedded_newlines_as_complete_fields():
    module = load_module("luca_ui_strings_under_test", GAME_TOOLS / "export_luca_ui_strings.py")
    first = "Drag in the message window to Rewind.\nAuto rewind by swiping (stop by tapping).".encode("utf-8")
    second = "Positioned at ❝Yes❞".encode("utf-8")
    data = b"\x01binary\0" + first + b"\0" + second + b"\0\xffinvalid\0"

    rows = list(module.iter_cstrings(data, 0, len(data)))
    assert rows == [
        (8, first),
        (9 + len(first), second),
    ]
