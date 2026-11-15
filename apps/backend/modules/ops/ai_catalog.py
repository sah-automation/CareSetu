"""Alias module for the AI provider catalog (issue #920)."""

from app.ai_provider_catalog import *  # noqa: F403
from app.ai_provider_catalog import get_ai_provider_catalog

ai_catalog = get_ai_provider_catalog
get_ai_catalog = get_ai_provider_catalog
load_ai_catalog = get_ai_provider_catalog
resolve_ai_catalog = get_ai_provider_catalog
catalog = get_ai_provider_catalog
