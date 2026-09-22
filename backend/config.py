"""
================================================================================
CONFIGURATION MODULE - APEX VOICE AGENT
================================================================================
This module loads configuration options and API keys from environment variables
or the local .env file.

Key components configured:
  1. Server networking (Host, Port)
  2. Audio specifications (16kHz 16-bit linear PCM mono)
  3. AssemblyAI Streaming STT WebSocket v3 API
  4. ElevenLabs Text-to-Speech credentials and voice presets
  5. Multi-Provider LLM credentials (Gemini, OpenAI, Anthropic, Groq)
  6. Conversational persona presets
================================================================================
"""

import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# Automatically locate and load .env file from project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


class AppConfig(BaseModel):
    # -------------------------------------------------------------------------
    # Server & Network Settings
    # -------------------------------------------------------------------------
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", 8000))
    
    # -------------------------------------------------------------------------
    # Audio Specifications
    # WebRTC and real-time STT standard: 16kHz, 16-bit linear PCM, mono.
    # -------------------------------------------------------------------------
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit PCM = 2 bytes per sample

    # -------------------------------------------------------------------------
    # 1. Speech-to-Text (STT) - AssemblyAI Streaming v3 WebSocket
    # https://www.assemblyai.com/
    # -------------------------------------------------------------------------
    assemblyai_api_key: str = os.getenv("ASSEMBLYAI_API_KEY", "")
    assemblyai_ws_url: str = os.getenv(
        "ASSEMBLYAI_WS_URL",
        "wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&speech_model=u3-rt-pro"
    )

    # -------------------------------------------------------------------------
    # 2. Text-to-Speech (TTS) - ElevenLabs Streaming API
    # https://elevenlabs.io/
    # -------------------------------------------------------------------------
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Default: Sarah (working premade)
    elevenlabs_model_id: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")

    # -------------------------------------------------------------------------
    # 3. Bring Your Own LLM (Gemini, OpenAI, Anthropic, Groq)
    # Default is 'gemini' (or 'mock' for local zero-cost testing)
    # -------------------------------------------------------------------------
    default_llm_provider: str = os.getenv("DEFAULT_LLM_PROVIDER", "gemini")
    
    # Google Gemini: https://aistudio.google.com/
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    
    # OpenAI: https://platform.openai.com/
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    # Anthropic: https://console.anthropic.com/
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    
    # Groq (Ultra-fast Llama/Qwen): https://console.groq.com/
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    # -------------------------------------------------------------------------
    # 4. Agent Persona Preset & Turn Latency Tuning
    # -------------------------------------------------------------------------
    agent_preset: str = os.getenv("AGENT_PRESET", "customer_support")
    turn_finalization_delay_ms: int = int(os.getenv("TURN_FINALIZATION_DELAY_MS", "400"))


# Global singleton configuration object
config = AppConfig()

