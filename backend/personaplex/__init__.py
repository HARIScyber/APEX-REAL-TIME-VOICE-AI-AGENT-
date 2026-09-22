"""
NVIDIA PersonaPlex / Moshi Voice Engine Integration Module.
Provides hardware detection, Hugging Face checkpoint management,
and unified voice engine integration with automatic fallback.
"""
from backend.personaplex.config import PersonaPlexConfig, personaplex_config
from backend.personaplex.personaplex_service import PersonaPlexService, get_personaplex_service

__all__ = [
    "PersonaPlexConfig",
    "personaplex_config",
    "PersonaPlexService",
    "get_personaplex_service",
]
