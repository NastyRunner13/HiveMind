"""
API Router — aggregates all route modules under the /api/v1 prefix.
"""

from fastapi import APIRouter

from app.api.channels import router as channels_router
from app.api.messages import router as messages_router

# Main API router — all sub-routers are included under this
api_router = APIRouter()

# Health check is at the root level (no /api/v1 prefix)
# Channels and messages are under /api/v1
api_router.include_router(channels_router, prefix="/channels", tags=["channels"])
api_router.include_router(messages_router, tags=["messages"])
