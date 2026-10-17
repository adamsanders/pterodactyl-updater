from pathlib import Path
from app.core.config import get_commit_code
from app.web.filters import discord_markdown
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
COMPONENTS_DIR = TEMPLATES_DIR / "components"

templates = Jinja2Templates(directory=[str(TEMPLATES_DIR), str(COMPONENTS_DIR)])
templates.env.filters["discord_md"] = discord_markdown
templates.env.globals["commit_code"] = get_commit_code()