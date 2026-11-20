"""Compatibility import surface; IAM routing lives in the IAM module."""

from app.modules.iam.router import router, v2_router

__all__ = ["router", "v2_router"]
