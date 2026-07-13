"""Non-secret instance metadata for the setup UI.

The Agent Setup page renders copy-paste plugin/MCP snippets. Sourcing the repo/marketplace
references from here (deployment config, §config.py) — instead of hardcoding them in the frontend
bundle — lets a fork or a self-hosted deployment point the instructions at *its* own repo.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import settings
from app.schemas.meta import SetupMeta

router = APIRouter()


@router.get("", response_model=SetupMeta)
async def get_meta(_: CurrentUser) -> SetupMeta:
    return SetupMeta(
        project_name=settings.PROJECT_NAME,
        plugin_marketplace_ref=settings.PLUGIN_MARKETPLACE_REF,
        plugin_repo_url=settings.PLUGIN_REPO_URL,
        plugin_mcp_server_path=settings.PLUGIN_MCP_SERVER_PATH,
    )
