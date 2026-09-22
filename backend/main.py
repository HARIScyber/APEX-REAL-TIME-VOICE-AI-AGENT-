"""
================================================================================
APEX REAL-TIME VOICE AI AGENT - BACKEND ENTRYPOINT
================================================================================
DATA FLOW:
  1. Client connects via WebSocket to /ws/voice
  2. Client streams raw 16kHz 16-bit linear PCM audio chunks
  3. Orchestrator passes audio to AssemblyAI Real-Time STT WebSocket
  4. STT emits live partial and final transcripts
  5. IntentEngine and LLMRouter stream tokens
  6. TTSService streams synthesized voice audio chunks back to the client
  7. If user speaks while assistant is talking, Barge-in immediately interrupts!

REST ENDPOINTS:
  GET  /api/health             - Aggregated subsystem health
  GET  /api/llm/health         - LLM provider reachability check
  GET  /api/stt/health         - STT configuration status
  GET  /api/tts/health         - TTS configuration status
  GET  /api/personaplex/health - PersonaPlex hardware status
  POST /api/chat               - Direct text→LLM→response test (no mic needed)
================================================================================
"""

import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from backend.config import config
from backend.orchestrator.conversation_manager import ConversationSession

# Configure structured console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("VoiceAgent")

# Initialize FastAPI Application
app = FastAPI(
    title="Apex Real-Time Voice AI Agent",
    description="Sub-second streaming voice assistant with AssemblyAI STT, Multi-LLM, and Barge-in.",
    version="1.1.0"
)

# Enable Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve path to the frontend directory
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """
    Aggregated health check — reports status of all subsystems.
    Does NOT report "ok" just because FastAPI is running.
    """
    from backend.personaplex import get_personaplex_service
    from backend.llm.llm_router import LLMRouter

    personaplex_diag = get_personaplex_service().get_diagnostics()

    # Quick non-blocking LLM reachability check
    llm_ok = False
    llm_error = None
    try:
        router = LLMRouter(
            provider=config.default_llm_provider,
            api_key=_get_llm_key(config.default_llm_provider),
            model_name=_get_llm_model(config.default_llm_provider),
        )
        health = await router.check_health()
        llm_ok = health.get("reachable", False)
        llm_error = health.get("last_error")
        await router.aclose()
    except Exception as exc:
        llm_error = str(exc)

    return {
        "status": "healthy",
        "stt": "ok" if config.assemblyai_api_key else "not_configured",
        "llm": "ok" if llm_ok else f"error: {llm_error}",
        "tts": "ok" if config.elevenlabs_api_key else "not_configured",
        "personaplex": "unavailable" if not personaplex_diag["is_hardware_supported"] else (
            "loaded" if personaplex_diag["is_loaded"] else "not_loaded"
        ),
        "assemblyai_configured": bool(config.assemblyai_api_key),
        "elevenlabs_configured": bool(config.elevenlabs_api_key),
        "default_llm_provider": config.default_llm_provider,
        "sample_rate": config.sample_rate,
        "personaplex_detail": personaplex_diag,
    }


@app.get("/api/llm/health")
async def llm_health():
    """
    Real LLM provider connectivity check.
    Reports: provider, model, configured, reachable, last_error.
    Does NOT expose credentials.
    """
    from backend.llm.llm_router import LLMRouter

    provider = config.default_llm_provider
    api_key = _get_llm_key(provider)
    model = _get_llm_model(provider)

    if provider == "mock":
        return {
            "provider": "mock",
            "model": "simulated-voice-llm",
            "configured": True,
            "reachable": True,
            "last_error": None,
            "mode": "MOCK — not a real LLM",
        }

    try:
        router = LLMRouter(provider=provider, api_key=api_key, model_name=model)
        result = await router.check_health()
        await router.aclose()
        return result
    except Exception as exc:
        return {
            "provider": provider,
            "model": model,
            "configured": bool(api_key),
            "reachable": False,
            "last_error": str(exc),
        }


@app.get("/api/stt/health")
async def stt_health():
    """AssemblyAI STT configuration status."""
    return {
        "provider": "assemblyai",
        "configured": bool(config.assemblyai_api_key),
        "sample_rate": config.sample_rate,
        "ws_url": config.assemblyai_ws_url,
        # Never expose the actual key
        "key_present": bool(config.assemblyai_api_key),
    }


@app.get("/api/tts/health")
async def tts_health():
    """ElevenLabs TTS configuration status."""
    return {
        "provider": "elevenlabs",
        "configured": bool(config.elevenlabs_api_key),
        "voice_id": config.elevenlabs_voice_id,
        "model_id": config.elevenlabs_model_id,
        "key_present": bool(config.elevenlabs_api_key),
    }


@app.get("/api/personaplex/health")
async def personaplex_health():
    """PersonaPlex / NVIDIA hardware status."""
    from backend.personaplex import get_personaplex_service
    diag = get_personaplex_service().get_diagnostics()
    return {
        "available": diag["is_hardware_supported"],
        "loaded": diag["is_loaded"],
        "load_status": diag["load_status"],
        "cuda_available": diag["cuda_available"],
        "gpu_name": diag["gpu_name"],
        "gpu_memory_gb": diag["gpu_memory_gb"],
        "hardware_message": diag["hardware_message"],
        "status_detail": diag["status_detail"],
        "model_load_time_ms": diag["model_load_time_ms"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEXT CHAT ENDPOINT (for testing without microphone)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """
    Direct text → LLM → streaming text response test endpoint.
    Used to validate the full LLM pipeline without microphone or TTS.

    Request body: {"message": "What is AI?", "provider": "gemini"} (provider optional)
    Response: Server-Sent Events (text/event-stream) of LLM tokens.

    This isolates LLM failures from STT/TTS/audio failures.
    """
    from backend.llm.llm_router import LLMRouter, LLMServiceError
    from backend.orchestrator.intent_engine import IntentEngine

    try:
        body = await request.json()
    except Exception:
        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes.decode("utf-8", errors="replace"))
        except Exception:
            return Response(
                content='{"error": "Invalid JSON body. Provide {\"message\": \"...\"}"}',
                status_code=400,
                media_type="application/json",
            )
    user_message = (body.get("message") or "").strip()
    if not user_message:
        return Response(content='{"error": "message field is required"}', status_code=400, media_type="application/json")

    provider = (body.get("provider") or config.default_llm_provider).lower()
    api_key = _get_llm_key(provider)
    model = _get_llm_model(provider)

    intent = IntentEngine(config.agent_preset)
    system_prompt = intent.get_system_prompt({"name": "Test User", "tier": "Standard"})
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    logger.info("[CHAT] /api/chat request: provider=%s message=%r", provider, user_message[:60])

    async def generate():
        router = LLMRouter(provider=provider, api_key=api_key, model_name=model)
        try:
            full = []
            async for token in router.stream_response(messages, tools_enabled=True):
                full.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, 'full_response': ''.join(full)})}\n\n"
            logger.info("[CHAT] Response complete: %d chars", sum(len(t) for t in full))
        except LLMServiceError as err:
            logger.error("[CHAT] LLM error: %s", err)
            yield f"data: {json.dumps({'error': str(err), 'stage': err.stage})}\n\n"
        except Exception as err:
            logger.exception("[CHAT] Unexpected error")
            yield f"data: {json.dumps({'error': str(err)})}\n\n"
        finally:
            await router.aclose()

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET VOICE ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.websocket("/ws/voice")
async def voice_websocket_endpoint(websocket: WebSocket):
    """
    Core Duplex WebSocket for Real-Time Voice Communication.

    INCOMING MESSAGES:
      - Binary frames: 16kHz 16-bit linear PCM microphone audio from browser.
      - JSON text frames:
          * {"type": "user_transcript", "text": "..."} -> Direct text turn.
          * {"type": "update_settings", "settings": {...}} -> Persona/provider update.
          * {"type": "interrupt"} -> Manual barge-in interrupt signal.
          * {"type": "ping"} -> Keepalive heartbeat.

    OUTGOING MESSAGES:
      - Binary frames: Synthesized MP3/PCM audio chunks from ElevenLabs TTS.
      - JSON text frames: partial_transcript, final_transcript, assistant_start,
          assistant_token, audio_chunk, interrupted, turn_complete, error.
    """
    await websocket.accept()
    session_id = str(uuid.uuid4())[:8]
    logger.info("[WS] New client connected. Session: %s", session_id)

    session = ConversationSession(session_id, websocket)
    await session.initialize()

    try:
        while True:
            message = await websocket.receive()

            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                logger.info("[WS] Client disconnected gracefully. Session: %s", session_id)
                break

            # 1. Binary audio frames (16kHz 16-bit PCM from browser mic)
            if "bytes" in message and message["bytes"]:
                await session.process_incoming_audio_chunk(message["bytes"])

            # 2. JSON control messages
            elif "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                    action_type = payload.get("type")

                    if action_type == "update_settings":
                        await session.update_settings(payload.get("settings", {}))
                        await session.send_json({
                            "type": "status",
                            "message": "Session settings updated successfully."
                        })

                    elif action_type == "user_transcript":
                        user_text = payload.get("text", "").strip()
                        if user_text:
                            await session.add_user_message(
                                user_text,
                                source=payload.get("source", "text"),
                                turn_id=payload.get("turn_id"),
                            )

                    elif action_type == "clear_chat":
                        await session.clear_chat()
                        await session.send_json({
                            "type": "status",
                            "message": "Conversation history cleared."
                        })

                    elif action_type == "interrupt":
                        await session.handle_user_barge_in(reason="manual_interrupt")

                    elif action_type == "ping":
                        await session.send_json({"type": "pong"})

                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        logger.info("[WS] WebSocket disconnected. Session: %s", session_id)
    except RuntimeError as re:
        if "Cannot call \"receive\"" not in str(re):
            logger.error("[WS] Runtime error in session %s: %s", session_id, re)
    except Exception as e:
        logger.error("[WS] Unexpected error in session %s: %s", session_id, e)
    finally:
        await session.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_llm_key(provider: str) -> str:
    return {
        "gemini": config.gemini_api_key,
        "openai": config.openai_api_key,
        "anthropic": config.anthropic_api_key,
        "groq": config.groq_api_key,
        "mock": "",
    }.get(provider.lower(), "")


def _get_llm_model(provider: str) -> str:
    return {
        "gemini": config.gemini_model,
        "openai": config.openai_model,
        "anthropic": config.anthropic_model,
        "groq": config.groq_model,
        "mock": "simulated-voice-llm",
    }.get(provider.lower(), config.gemini_model)


# ─────────────────────────────────────────────────────────────────────────────
# STATIC FRONTEND
# ─────────────────────────────────────────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_index():
        """Serve the main single-page voice application."""
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=config.host, port=config.port, reload=True)
