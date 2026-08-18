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


def test_approved_opening_titles_render_as_bright_centered_rgba():
    module = load_module(
        "luca_opening_images_under_test",
        GAME_TOOLS / "build_luca_opening_images.py",
    )
    assert module.TITLE_CONFIG["status"] == "approved"
    assert module.TITLE_CONFIG["approved_by"] == "user"
    assert module.TITLE_CONFIG["render"]["long_line_policy"] == "horizontal_scale_only"
    assert [row["entry_id"] for row in module.TITLE_ROWS] == list(range(25257, 25306, 3))
    rendered = module.render_all()
    assert len(rendered) == 17
    assert rendered[0].compression == 1.0
    assert min(title.compression for title in rendered) < 1.0

    for title in rendered:
        assert title.image.mode == "RGBA"
        assert title.image.size == module.CANVAS_SIZE
        left, top, right, bottom = title.alpha_bbox
        assert right - left <= module.MAX_TEXT_WIDTH + 100
        assert abs((left + right) / 2 - module.TEXT_CENTER[0]) <= 1
        assert abs((top + bottom) / 2 - module.TEXT_CENTER[1]) <= 1
        assert title.image.getchannel("A").getextrema() == (0, 255)
        assert (255, 255, 255, 255) in title.image.get_flattened_data()


def test_scaled_alpha_clamps_values():
    module = load_module(
        "luca_opening_images_alpha_under_test",
        GAME_TOOLS / "build_luca_opening_images.py",
    )
    from PIL import Image

    source = Image.frombytes("L", (2, 1), bytes((200, 10)))
    result = module._scaled_alpha(source, 2.0)
    assert list(result.get_flattened_data()) == [255, 20]
