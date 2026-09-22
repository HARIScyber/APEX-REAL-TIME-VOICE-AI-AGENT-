import asyncio
import logging
import re
from typing import AsyncGenerator, Optional

import httpx

logger = logging.getLogger(__name__)

SENTENCE_SPLIT_REGEX = re.compile(r"([.?!;:]+[\s\n]+|\n+)")


class TextChunker:
    """Buffers token fragments until a speakable sentence is available."""

    def __init__(self, min_chunk_words: int = 4):
        self.buffer = ""
        self.min_chunk_words = min_chunk_words

    def add_token(self, token: str) -> Optional[str]:
        self.buffer += token
        # Scan through all delimiter matches until one has enough words
        for match in SENTENCE_SPLIT_REGEX.finditer(self.buffer):
            candidate = self.buffer[: match.end()].strip()
            if len(candidate.split()) >= self.min_chunk_words:
                self.buffer = self.buffer[match.end():]
                return candidate
        return None

    def flush(self) -> Optional[str]:
        text = self.buffer.strip()
        self.buffer = ""
        return text or None


class TTSService:
    """
    Streams ElevenLabs PCM audio using one reusable async HTTP client.

    Audio format: pcm_16000 — signed 16-bit little-endian PCM, mono, 16kHz.
    Every chunk yielded is guaranteed to have an even byte length (complete samples).
    """

    def __init__(
        self,
        api_key: str = "",
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        model_id: str = "eleven_flash_v2_5",
    ):
        self.api_key = api_key.strip()
        self.voice_id = voice_id
        self.model_id = model_id
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
        logger.info(
            "[TTS] Service initialized. voice_id=%s model_id=%s format=pcm_16000",
            self.voice_id,
            self.model_id,
        )

    async def stream_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Yield signed 16-bit little-endian PCM frames as they arrive.

        Audio format: pcm_s16le, 16000 Hz, mono.
        Each yielded chunk has an even byte length (2 bytes per sample).
        An odd-length trailing byte is held in a carry buffer and prepended
        to the next chunk so no audio data is dropped.
        """
        if not self.api_key or not text.strip():
            logger.warning("[TTS] stream_audio called with missing key or empty text")
            return

        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
            "?output_format=pcm_16000&optimize_streaming_latency=3"
        )
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "use_speaker_boost": True,
            },
        }
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json"}

        logger.debug("[TTS] request text=%r model=%s voice=%s", text[:60], self.model_id, self.voice_id)

        carry = b""  # Carry odd trailing byte between chunks
        total_bytes = 0
        chunk_count = 0

        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    body_text = body.decode("utf-8", errors="replace")[:200]
                    logger.error(
                        "[TTS] ElevenLabs request failed: status=%d body=%s",
                        response.status_code,
                        body_text,
                    )
                    return

                async for raw_chunk in response.aiter_bytes(chunk_size=2048):
                    if not raw_chunk:
                        continue
                    # Prepend any carry byte from previous chunk
                    chunk = carry + raw_chunk
                    carry = b""

                    # If chunk has odd length, carry the last byte to next iteration
                    if len(chunk) % 2 != 0:
                        carry = chunk[-1:]
                        chunk = chunk[:-1]

                    if len(chunk) >= 2:
                        total_bytes += len(chunk)
                        chunk_count += 1
                        yield chunk

                # If there's a lingering carry byte at end of stream, log and discard
                if carry:
                    logger.debug("[TTS] Discarded 1 trailing odd byte at stream end")

        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            logger.error("[TTS] ElevenLabs connection failed: %s", type(exc).__name__)

        if chunk_count > 0:
            duration_ms = round(total_bytes / 2 / 16000 * 1000, 1)
            logger.debug(
                "[TTS] stream complete: chunks=%d bytes=%d duration=%.1fms",
                chunk_count,
                total_bytes,
                duration_ms,
            )

    async def aclose(self) -> None:
        await self._client.aclose()
