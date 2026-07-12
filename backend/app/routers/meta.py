"""Meta / config endpoints for frontend registries (field labels)."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.services.glossary import load_field_labels

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/field-labels")
def field_labels():
    """Serve config/field_labels.json — single source for Label component."""
    data = load_field_labels()
    # strip _meta from lookup keys but keep it for clients that want version
    return data
