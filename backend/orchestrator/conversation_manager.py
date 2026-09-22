import asyncio
import base64
import json
import logging
import time
from typing import Optional

from fastapi import WebSocket

from backend.audio_processing.vad import VoiceActivityDetector
from backend.config import config
from backend.llm.llm_router import LLMRouter, LLMServiceError
from backend.orchestrator.intent_engine import IntentEngine
from backend.orchestrator.state_memory import StateMemory
from backend.orchestrator.voice_engine import VoiceEngineRouter, VoiceEngineMode
from backend.personaplex import get_personaplex_service
from backend.stt.assemblyai_stt import AssemblyAIRealtimeSTT
from backend.tts.tts_service import TTSService, TextChunker

logger = logging.getLogger(__name__)


class ConversationSession:
    """Owns one turn-scoped, cancel-safe streaming voice conversation."""

    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.ws = websocket
        self.memory = StateMemory(session_id)
        self.intent_engine = IntentEngine(config.agent_preset)
        self.engine_router = VoiceEngineRouter(VoiceEngineMode.ASSEMBLYAI)
        self.personaplex_service = get_personaplex_service()
        self.vad = VoiceActivityDetector(energy_threshold_db=-40.0, silence_timeout_ms=650)
        self.stt_client: Optional[AssemblyAIRealtimeSTT] = None
        self.llm_router = LLMRouter(
            provider=config.default_llm_provider,
            api_key=self._get_initial_llm_key(config.default_llm_provider),
            model_name=self._get_initial_llm_model(config.default_llm_provider),
        )
        self.tts_service = TTSService(
            api_key=config.elevenlabs_api_key,
            voice_id=config.elevenlabs_voice_id,
            model_id=config.elevenlabs_model_id,
        )
        self.active_turn_task: Optional[asyncio.Task] = None
        self.turn_counter = 0
        self.active_turn_id: Optional[str] = None
        self.is_speaking = False
        self.latest_partial_transcript = ""
        self._recent_messages: dict[str, float] = {}
        self._send_lock = asyncio.Lock()
        self._last_audio_at: Optional[float] = None
        self._stt_latency_ms: Optional[float] = None
        self._turn_detection_latency_ms: Optional[float] = None

        logger.info(
            "[SESSION %s] Initialized. LLM provider=%s model=%s",
            session_id,
            self.llm_router.provider,
            self.llm_router.model_name,
        )

    @staticmethod
    def _get_initial_llm_key(provider: str) -> str:
        return {
            "gemini": config.gemini_api_key,
            "openai": config.openai_api_key,
            "anthropic": config.anthropic_api_key,
            "groq": config.groq_api_key,
        }.get(provider.lower(), "")

    @staticmethod
    def _get_initial_llm_model(provider: str) -> Optional[str]:
        return {
            "gemini": config.gemini_model,
            "openai": config.openai_model,
            "anthropic": config.anthropic_model,
            "groq": config.groq_model,
        }.get(provider.lower())

    async def initialize(self) -> None:
        if not config.assemblyai_api_key:
            logger.warning("[STT] AssemblyAI API key not configured — STT disabled")
            await self.send_json({"type": "status", "message": "Speech transcription is not configured.", "stt_active": False})
            return
        try:
            self.stt_client = AssemblyAIRealtimeSTT(
                api_key=config.assemblyai_api_key,
                sample_rate=config.sample_rate,
                on_partial_transcript=self.on_stt_partial,
                on_final_transcript=self.on_stt_final,
                on_error=self.on_stt_error,
            )
            await self.stt_client.connect()
            logger.info("[STT] AssemblyAI connected. sample_rate=%d", config.sample_rate)
            await self.send_json({"type": "status", "message": "Speech transcription connected.", "stt_active": True})
        except Exception as exc:
            logger.exception("[STT] Unable to initialize AssemblyAI STT: %s", exc)
            self.stt_client = None
            await self.send_json({
                "type": "status",
                "message": f"Speech transcription connection failed: {exc}",
                "stt_active": False,
            })

    async def send_json(self, data: dict) -> None:
        try:
            async with self._send_lock:
                await self.ws.send_text(json.dumps(data))
        except Exception:
            logger.debug("[WS] Client WebSocket is unavailable — send skipped")

    async def handle_user_barge_in(self, reason: str = "speech_detected") -> None:
        if not self.is_speaking and not (self.active_turn_task and not self.active_turn_task.done()):
            return
        previous_turn = self.active_turn_id
        self.turn_counter += 1
        self.active_turn_id = None
        if self.active_turn_task and not self.active_turn_task.done():
            logger.info("[TURN %s] barge_in reason=%s — cancelling active task", previous_turn, reason)
            self.active_turn_task.cancel()
            try:
                await self.active_turn_task
            except asyncio.CancelledError:
                pass
        self.active_turn_task = None
        self.is_speaking = False
        await self.send_json({"type": "interrupted", "turn_id": previous_turn, "reason": reason})
        logger.info("[TURN %s] interrupted", previous_turn)

    async def on_stt_partial(self, text: str) -> None:
        self.latest_partial_transcript = text.strip()
        if self._last_audio_at is not None and self._stt_latency_ms is None:
            self._stt_latency_ms = round((time.perf_counter() - self._last_audio_at) * 1000, 1)
        await self.send_json({"type": "partial_transcript", "text": self.latest_partial_transcript})

    async def on_stt_final(self, text: str, confidence: float) -> None:
        self.latest_partial_transcript = ""
        logger.info("[STT] final transcript=%r confidence=%.2f", text, confidence)
        await self.add_user_message(text, source="stt", confidence=confidence)

    async def on_stt_error(self, error: str) -> None:
        logger.warning("[STT] AssemblyAI error: %s", error)
        await self.send_json({
            "type": "error",
            "source": "stt",
            "message": "Speech transcription is temporarily unavailable.",
            "detail": error,
        })

    async def process_incoming_audio_chunk(self, pcm_bytes: bytes) -> None:
        self._last_audio_at = time.perf_counter()
        vad_event = self.vad.process_chunk(pcm_bytes)
        # Only interrupt on the FIRST frame of a new speech event (speech_started),
        # not on every subsequent confirmed-speech frame — that was causing barge-in spam.
        if vad_event["speech_started"] and self.is_speaking:
            logger.info("[VAD] speech_started detected while agent speaking — triggering barge-in")
            await self.handle_user_barge_in("confirmed_user_speech")
        if vad_event["speech_ended"]:
            if self._last_audio_at is not None:
                self._turn_detection_latency_ms = round(
                    (time.perf_counter() - self._last_audio_at) * 1000, 1
                )
            await self.send_json({"type": "vad_state", "state": "speech_ended"})
        if self.stt_client:
            await self.stt_client.send_audio(pcm_bytes)

    async def add_user_message(
        self, message: str, source: str, turn_id: Optional[str] = None, confidence: Optional[float] = None
    ) -> Optional[str]:
        text = message.strip()
        if not text:
            return None

        # Deduplicate: ignore identical message within 2 seconds (prevents double-fire from STT)
        now = time.monotonic()
        fingerprint = text.casefold()
        if now - self._recent_messages.get(fingerprint, 0.0) < 2.0:
            logger.info("[TURN] Ignored duplicate user message from %s: %r", source, text[:50])
            return None
        self._recent_messages = {k: v for k, v in self._recent_messages.items() if now - v < 5.0}
        self._recent_messages[fingerprint] = now

        await self.handle_user_barge_in("new_user_turn")
        self.turn_counter += 1
        current_turn_id = turn_id or f"turn_{self.turn_counter:04d}"
        self.active_turn_id = current_turn_id

        logger.info("[TURN %s] speech_started source=%s text=%r", current_turn_id, source, text[:80])

        payload = {"type": "final_transcript", "text": text, "turn_id": current_turn_id, "source": source}
        if confidence is not None:
            payload["confidence"] = confidence
        await self.send_json(payload)

        self.active_turn_task = asyncio.create_task(
            self._execute_turn(text, current_turn_id, source)
        )
        return current_turn_id

    async def _execute_turn(self, user_text: str, turn_id: str, source: str) -> None:
        started_at = time.perf_counter()
        first_token_at: Optional[float] = None
        first_audio_at: Optional[float] = None
        llm_finished_at: Optional[float] = None
        tts_started_at: Optional[float] = None
        full_response: list[str] = []
        tts_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        chunker = TextChunker(min_chunk_words=3)

        route = self.engine_router.select_target_pipeline(user_text)
        tools_enabled = (route["request_type"] != "simple_conversation")

        self.memory.add_message("user", user_text, turn_id=turn_id, source=source)
        messages = self.memory.get_messages_for_llm(
            self.intent_engine.get_system_prompt(self.memory.user_preferences)
        )
        self.is_speaking = True
        await self.send_json({
            "type": "assistant_start",
            "turn_id": turn_id,
            "engine": route["engine"],
            "request_type": route["request_type"],
            "fallback_active": route["fallback_active"],
            "route_reason": route["reason"],
        })

        logger.info(
            "[TURN %s] llm_start provider=%s model=%s tools=%s",
            turn_id, self.llm_router.provider, self.llm_router.model_name, tools_enabled
        )

        async def tts_worker() -> None:
            nonlocal first_audio_at, tts_started_at
            chunk_index = 0
            while True:
                sentence = await tts_queue.get()
                try:
                    if sentence is None:
                        return
                    if turn_id != self.active_turn_id:
                        logger.debug("[TTS] Discarding sentence for stale turn %s", turn_id)
                        return
                    if tts_started_at is None:
                        tts_started_at = time.perf_counter()
                        logger.info("[TURN %s] tts_start", turn_id)

                    sent_audio = False
                    t_tts = time.perf_counter()
                    async for audio_chunk in self.tts_service.stream_audio(sentence):
                        if turn_id != self.active_turn_id:
                            logger.debug("[TTS] Discarding audio chunk — turn changed")
                            return
                        if first_audio_at is None:
                            first_audio_at = time.perf_counter()
                            logger.info(
                                "[TURN %s] audio_start ttfa=%.1fms",
                                turn_id,
                                (first_audio_at - started_at) * 1000,
                            )
                        sent_audio = True
                        chunk_index += 1
                        await self.send_json({
                            "type": "audio_chunk",
                            "turn_id": turn_id,
                            "format": "pcm_s16le",
                            "sample_rate": config.sample_rate,
                            "audio": base64.b64encode(audio_chunk).decode("ascii"),
                        })

                    if sent_audio:
                        logger.debug(
                            "[TTS] sentence done. chunk=%d tts_time=%.1fms text=%r",
                            chunk_index,
                            (time.perf_counter() - t_tts) * 1000,
                            sentence[:50],
                        )
                    elif turn_id == self.active_turn_id:
                        logger.warning("[TTS] No audio returned for sentence — sending browser TTS fallback")
                        await self.send_json({
                            "type": "tts_fallback",
                            "turn_id": turn_id,
                            "text": sentence,
                            "reason": "ElevenLabs returned empty audio",
                        })
                finally:
                    tts_queue.task_done()

        worker = asyncio.create_task(tts_worker())
        try:
            token_count = 0
            async for token in self.llm_router.stream_response(messages, tools_enabled=tools_enabled):
                if turn_id != self.active_turn_id:
                    logger.debug("[LLM] Discarding token — turn changed (barge-in)")
                    return
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                    logger.info(
                        "[TURN %s] llm_first_chunk ttft=%.1fms",
                        turn_id,
                        (first_token_at - started_at) * 1000,
                    )
                token_count += 1
                full_response.append(token)
                await self.send_json({"type": "assistant_token", "turn_id": turn_id, "token": token})
                sentence = chunker.add_token(token)
                if sentence:
                    await tts_queue.put(sentence)

            remaining = chunker.flush()
            if remaining:
                await tts_queue.put(remaining)

            llm_finished_at = time.perf_counter()
            logger.info(
                "[TURN %s] llm_complete tokens=%d llm_time=%.1fms",
                turn_id,
                token_count,
                (llm_finished_at - started_at) * 1000,
            )

            await tts_queue.put(None)  # Signal TTS worker to finish
            await worker  # Wait for all audio to be sent

            response = "".join(full_response).strip()
            if response:
                self.memory.add_message("assistant", response, turn_id=turn_id, source="llm")

            finished_at = time.perf_counter()
            diag = self.personaplex_service.get_diagnostics()

            logger.info(
                "[TURN %s] completed total=%.1fms",
                turn_id,
                (finished_at - started_at) * 1000,
            )

            await self.send_json({
                "type": "turn_complete",
                "turn_id": turn_id,
                "engine": route["engine"],
                "request_type": route["request_type"],
                "fallback_active": route["fallback_active"],
                "route_reason": route["reason"],
                "metrics": {
                    "stt_latency_ms": self._stt_latency_ms or 0.0,
                    "turn_detection_ms": self._turn_detection_latency_ms or 0.0,
                    "ttft_ms": self._elapsed_ms(first_token_at, started_at),
                    "llm_total_ms": self._elapsed_ms(llm_finished_at, started_at),
                    "tool_latency_ms": self.llm_router.last_tool_latency_ms,
                    "rag_latency_ms": self.llm_router.last_rag_latency_ms,
                    "tts_ttfa_ms": self._elapsed_ms(first_audio_at, started_at),
                    "tts_total_ms": self._elapsed_ms(finished_at, tts_started_at),
                    "total_ms": self._elapsed_ms(finished_at, started_at),
                    "personaplex_load_ms": diag["model_load_time_ms"],
                    "personaplex_inference_ms": diag["last_inference_latency_ms"],
                    "personaplex_ttfa_ms": diag["last_ttfa_ms"],
                    "personaplex_total_ms": diag["last_total_ms"],
                    "personaplex_status": diag["load_status"],
                    "personaplex_hardware": diag["hardware_message"],
                },
            })

        except LLMServiceError as error:
            logger.error("[TURN %s] LLM error: %s", turn_id, error)
            spoken_fallback = "I am temporarily experiencing high demand from the language service. Please ask me again in just a moment."
            await self.send_json({"type": "assistant_token", "turn_id": turn_id, "token": spoken_fallback})
            try:
                await tts_queue.put(spoken_fallback)
                await tts_queue.put(None)
                await asyncio.wait_for(worker, timeout=5.0)
            except Exception:
                pass
            await self.send_json({
                "type": "turn_complete",
                "turn_id": turn_id,
                "engine": route["engine"],
                "request_type": route["request_type"],
                "fallback_active": True,
                "route_reason": "llm_rate_limit_fallback",
                "metrics": {
                    "stt_latency_ms": self._stt_latency_ms or 0.0,
                    "turn_detection_ms": self._turn_detection_latency_ms or 0.0,
                    "ttft_ms": 0.0,
                    "llm_total_ms": 0.0,
                    "tool_latency_ms": 0.0,
                    "rag_latency_ms": 0.0,
                    "first_audio_ms": 0.0,
                    "tts_latency_ms": 0.0,
                    "total_roundtrip_ms": self._elapsed_ms(time.perf_counter(), started_at),
                    "personaplex_load_ms": 0.0,
                    "personaplex_inference_ms": 0.0,
                    "personaplex_ttfa_ms": 0.0,
                    "personaplex_total_ms": 0.0,
                    "personaplex_hardware": "N/A",
                },
            })
        except asyncio.CancelledError:
            logger.info("[TURN %s] Cancelled (barge-in or session close)", turn_id)
            raise
        except Exception as exc:
            logger.exception("[TURN %s] Unhandled turn error: %s", turn_id, exc)
            await self.send_json({
                "type": "error",
                "source": "turn",
                "stage": "orchestration",
                "turn_id": turn_id,
                "message": "I could not complete that request. Please try again.",
                "detail": str(exc),
                "recoverable": True,
            })
        finally:
            if not worker.done():
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
            if self.active_turn_id == turn_id:
                self.is_speaking = False

    @staticmethod
    def _elapsed_ms(end: Optional[float], start: Optional[float]) -> float:
        return round((end - start) * 1000, 1) if end is not None and start is not None else 0.0

    async def update_settings(self, settings: dict) -> None:
        engine = settings.get("voice_engine")
        if engine:
            self.engine_router.set_mode(engine)
            logger.info("[SESSION] Voice engine mode updated to: %s", self.engine_router.mode.value)

        provider = settings.get("llm_provider")
        if provider:
            logger.info(
                "[SESSION] LLM provider change requested: %s -> %s",
                self.llm_router.provider,
                provider,
            )
            await self.handle_user_barge_in("provider_changed")
            previous_router = self.llm_router
            self.llm_router = LLMRouter(
                provider=provider,
                api_key=self._get_initial_llm_key(provider),
                model_name=self._get_initial_llm_model(provider),
            )
            logger.info(
                "[LLM] Switched to provider=%s model=%s",
                self.llm_router.provider,
                self.llm_router.model_name,
            )
            await previous_router.aclose()

        if "agent_preset" in settings:
            self.intent_engine.set_preset(settings["agent_preset"])

    async def clear_chat(self) -> None:
        await self.handle_user_barge_in("clear_chat")
        self.memory.clear_history()
        self.latest_partial_transcript = ""
        self._recent_messages.clear()
        self.vad.reset()
        logger.info("[SESSION %s] Chat history cleared", self.session_id)

    async def cleanup(self) -> None:
        logger.info("[SESSION %s] Cleaning up", self.session_id)
        await self.handle_user_barge_in("session_closed")
        if self.stt_client:
            await self.stt_client.close()
            self.stt_client = None
        await self.tts_service.aclose()
        await self.llm_router.aclose()
