"""Non-secret instance metadata for the setup UI (and the trackers this instance can mirror).

The Agent Setup page renders copy-paste plugin/MCP snippets. Sourcing the repo/marketplace
references from here (deployment config, §config.py) — instead of hardcoding them in the frontend
bundle — lets a fork or a self-hosted deployment point the instructions at *its* own repo.
"""

from dataclasses import asdict

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.connectors.tracker import registered_trackers, tracker_enabled
from app.core.config import settings
from app.schemas.meta import SetupMeta, TrackerCapabilitiesRead, TrackerMeta, TrackersMeta

router = APIRouter()


@router.get("", response_model=SetupMeta)
async def get_meta(_: CurrentUser) -> SetupMeta:
    return SetupMeta(
        project_name=settings.PROJECT_NAME,
        plugin_marketplace_ref=settings.PLUGIN_MARKETPLACE_REF,
        plugin_repo_url=settings.PLUGIN_REPO_URL,
        plugin_mcp_server_path=settings.PLUGIN_MCP_SERVER_PATH,
    )


@router.get("/trackers", response_model=TrackersMeta)
async def list_trackers(_: CurrentUser) -> TrackersMeta:
    """The work trackers this instance knows, with what each supports — the Connectors form and
    a project's Tracking panel render from this, so a new tracker needs no UI change."""
    out: list[TrackerMeta] = []
    for provider, cls in sorted(registered_trackers().items(), key=lambda kv: kv[0].value):
        webhooks = cls.capabilities.webhooks
        out.append(
            TrackerMeta(
                provider=provider.value,
                label=cls.label or provider.value,
                enabled=tracker_enabled(provider),
                capabilities=TrackerCapabilitiesRead(**asdict(cls.capabilities)),
                config_schema=cls.config_schema.model_json_schema(),
                scope_schema=cls.scope_schema.model_json_schema(),
                webhook_path=f"/webhooks/{provider.value}" if webhooks else None,
                webhook_secret_setting=f"{provider.value.upper()}_WEBHOOK_SECRET"
                if webhooks
                else None,
            )
        )
    return TrackersMeta(trackers=out, default_tracking_mode=settings.TRACKING_DEFAULT_MODE)
