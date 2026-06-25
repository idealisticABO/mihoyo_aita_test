"""Templates package — Blender / reconstruct python templates."""
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent
RENDER_TEMPLATE = TEMPLATE_DIR / "render_template.py"
RECONSTRUCT_TEMPLATE = TEMPLATE_DIR / "reconstruct_template.py"
