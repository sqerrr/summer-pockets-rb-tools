"""Repository and game paths.

The root is found by walking up to AGENTS.md, so scripts work from any
subdirectory and the checkout can live anywhere. Game locations come from
config/project.yaml rather than being repeated in every script.
"""
from pathlib import Path
import sys

import yaml

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "AGENTS.md").exists())

with open(ROOT / "config" / "project.yaml", encoding="utf-8") as _fh:
    CONFIG = yaml.safe_load(_fh)

_game = CONFIG["game"]
GAME_DIR = ROOT / _game["install_dir"]
SCENE_PCK = ROOT / _game["scene_pack"]
SCENE_PCK_ORIG = ROOT / _game["scene_pack_original"]
GAME_EXE = ROOT / _game["executable"]
DAT_DIR = GAME_DIR / "dat"
FONT01 = DAT_DIR / "font01.ttf"
FONT02 = DAT_DIR / "font02.ttf"

# Debug screenshots are throwaway and stay out of git; see .gitignore.
SHOTS_DIR = ROOT / "game-tools" / "shots"


def ensure_importable() -> None:
    """Let probes and harnesses import siglus.py from game-tools/."""
    d = str(ROOT / "game-tools")
    if d not in sys.path:
        sys.path.insert(0, d)


def require_game() -> None:
    """Fail early and clearly when the game is not where the config says."""
    if not GAME_DIR.exists():
        raise SystemExit(
            f"Game not found at {GAME_DIR}\n"
            f"Fix game.install_dir in {ROOT / 'config' / 'project.yaml'}")
