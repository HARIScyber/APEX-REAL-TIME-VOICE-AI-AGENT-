"""
Voice Engine Abstraction and Routing Module.
Supports:
  1. 'assemblyai' (Default): AssemblyAI v3 Real-time STT + Gemini Streaming LLM + TextChunker + TTS.
  2. 'personaplex': NVIDIA PersonaPlex 7B Audio-to-Audio streaming with automatic fallback.
  3. 'hybrid': Intelligent router:
       - Simple conversational pleasantries & chitchat -> PersonaPlex
       - Complex / application / tool / RAG requests -> Gemini + RAG + Tools
"""
import enum
import logging
import re
from typing import Optional, Dict, Any

from backend.personaplex.personaplex_service import get_personaplex_service, PersonaPlexUnavailableError

logger = logging.getLogger(__name__)


class VoiceEngineMode(str, enum.Enum):
    ASSEMBLYAI = "assemblyai"
    PERSONAPLEX = "personaplex"
    HYBRID = "hybrid"


# Regex patterns identifying queries that require tools, RAG, or deep knowledge reasoning
COMPLEX_INTENT_PATTERNS = [
    re.compile(r"\b(order|ord-\d+|track|tracking|status|shipment|delivery)\b", re.IGNORECASE),
    re.compile(r"\b(policy|return|refund|warranty|guarantee|terms)\b", re.IGNORECASE),
    re.compile(r"\b(light|lights|thermostat|ac|temperature|fan|door|lock|home)\b", re.IGNORECASE),
    re.compile(r"\b(calculate|compute|math|equation|database|sql|search|rag)\b", re.IGNORECASE),
    re.compile(r"\b(weather|forecast|temperature in|how hot|how cold)\b", re.IGNORECASE),
    re.compile(r"\b(appointment|schedule|book|reschedule|cancel booking)\b", re.IGNORECASE),
]


class VoiceEngineRouter:
    """Manages voice engine mode selection, request type determination, and fallback."""

    def __init__(self, mode: VoiceEngineMode = VoiceEngineMode.ASSEMBLYAI):
        self.mode = mode
        self.personaplex = get_personaplex_service()

    def set_mode(self, mode_str: str) -> VoiceEngineMode:
        """Update active engine mode. Defaults safely to ASSEMBLYAI."""
        mode_str = mode_str.lower().strip()
        if mode_str == VoiceEngineMode.PERSONAPLEX.value:
            self.mode = VoiceEngineMode.PERSONAPLEX
        elif mode_str == VoiceEngineMode.HYBRID.value:
            self.mode = VoiceEngineMode.HYBRID
        else:
            self.mode = VoiceEngineMode.ASSEMBLYAI
        return self.mode

    def classify_request(self, user_text: str) -> str:
        """
        Determine if request is 'simple' or 'complex'.
        Simple: greetings, chit-chat, casual voice interaction.
        Complex: requires tools, RAG, database lookup, device control, or multi-step logic.
        """
        text = user_text.strip()
        if not text:
            return "simple"

        # Check for complex intent keywords
        for pattern in COMPLEX_INTENT_PATTERNS:
            if pattern.search(text):
                return "complex"

        # Long questions or questions with specific interrogatives tend to be complex
        word_count = len(text.split())
        if word_count > 15:
            return "complex"

        return "simple"

    def select_target_pipeline(self, user_text: str) -> Dict[str, Any]:
        """
        Resolves the execution engine for a turn.
        Returns target engine, request type, and fallback status.
        """
        diag = self.personaplex.get_diagnostics()
        personaplex_ready = diag["is_loaded"]

        if self.mode == VoiceEngineMode.PERSONAPLEX:
            if personaplex_ready:
                return {
                    "engine": "personaplex",
                    "request_type": "audio_to_audio",
                    "fallback_active": False,
                    "reason": "PersonaPlex mode active",
                }
            else:
                logger.info(
                    "PersonaPlex unavailable (%s), falling back to AssemblyAI pipeline",
                    diag["load_status"]
                )
                return {
                    "engine": "assemblyai",
                    "request_type": "fallback_pipeline",
                    "fallback_active": True,
                    "reason": f"PersonaPlex fallback: {diag['status_detail']}",
                }

        elif self.mode == VoiceEngineMode.HYBRID:
            req_type = self.classify_request(user_text)
            if req_type == "simple" and personaplex_ready:
                return {
                    "engine": "personaplex",
                    "request_type": "simple_conversation",
                    "fallback_active": False,
                    "reason": "Routed simple conversation to PersonaPlex",
                }
            else:
                return {
                    "engine": "assemblyai",
                    "request_type": "complex_request" if req_type == "complex" else "simple_fallback",
                    "fallback_active": (req_type == "simple" and not personaplex_ready),
                    "reason": "Routed to Gemini + RAG + Tools" if req_type == "complex" else "PersonaPlex unavailable; fallback to Gemini",
                }

        # Default mode: ASSEMBLYAI
        return {
            "engine": "assemblyai",
            "request_type": "standard",
            "fallback_active": False,
            "reason": "Default AssemblyAI + Gemini + TTS pipeline",
        }
