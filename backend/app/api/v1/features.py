"""The effective feature map, readable by every authenticated client.

The React app hides gated navigation/tabs from this map (refetched on the `features` SSE
event); the MCP `get_enabled_features` tool reads it so Claude picks tools that are on.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas.admin import FeatureMap
from app.services.features import effective_features

router = APIRouter()


@router.get("", response_model=FeatureMap)
async def get_features(session: SessionDep, _: CurrentUser) -> FeatureMap:
    return FeatureMap(features=await effective_features(session))
