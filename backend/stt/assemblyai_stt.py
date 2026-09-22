import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import websockets

logger = logging.getLogger(__name__)


class AssemblyAIRealtimeSTT:
    """AssemblyAI v3 PCM streaming client with serialized WebSocket lifecycle."""

    def __init__(
        self,
        api_key: str,
        sample_rate: int = 16000,
        on_partial_transcript: Optional[Callable[[str], Awaitable[None]]] = None,
        on_final_transcript: Optional[Callable[[str, float], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.api_key = api_key.strip()
        self.sample_rate = sample_rate
        self.ws_url = f"wss://streaming.assemblyai.com/v3/ws?sample_rate={sample_rate}&speech_model=u3-rt-pro"
        self.on_partial_transcript = on_partial_transcript
        self.on_final_transcript = on_final_transcript
        self.on_error = on_error
        self._ws = None
        self._receive_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._send_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    async def connect(self) -> None:
        if not self.api_key:
            raise ValueError("AssemblyAI is not configured")
        if self._is_running:
            return
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                headers = {"Authorization": self.api_key}
                try:
                    self._ws = await asyncio.wait_for(
                        websockets.connect(self.ws_url, additional_headers=headers, ping_interval=20, ping_timeout=20),
                        timeout=8.0,
                    )
                except TypeError:
                    self._ws = await asyncio.wait_for(
                        websockets.connect(self.ws_url, extra_headers=headers, ping_interval=20, ping_timeout=20),
                        timeout=8.0,
                    )
                self._is_running = True
                self._receive_task = asyncio.create_task(self._listen_loop())
                return
            except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as error:
                last_error = error
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
        raise ConnectionError("Unable to connect to AssemblyAI") from last_error

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or not self._is_running or not self._ws:
            return
        try:
            async with self._send_lock:
                if self._is_running and self._ws:
                    await self._ws.send(pcm_bytes)
        except (OSError, websockets.WebSocketException) as error:
            logger.warning("AssemblyAI audio send failed: %s", type(error).__name__)
            if self.on_error:
                await self.on_error("connection")

    async def _listen_loop(self) -> None:
        try:
            assert self._ws is not None
            async for raw_message in self._ws:
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                message_type = data.get("type") or data.get("message_type", "")
                if message_type == "Turn":
                    transcript = data.get("transcript", "").strip()
                    if not transcript:
                        continue
                    if data.get("end_of_turn", False):
                        if self.on_final_transcript:
                            await self.on_final_transcript(transcript, float(data.get("confidence", 1.0)))
                    elif self.on_partial_transcript:
                        await self.on_partial_transcript(transcript)
                elif message_type in {"Termination", "SessionTerminated"}:
                    break
                elif data.get("error") and self.on_error:
                    await self.on_error("service")
        except asyncio.CancelledError:
            raise
        except (OSError, websockets.WebSocketException) as error:
            logger.warning("AssemblyAI listener ended: %s", type(error).__name__)
            if self.on_error:
                await self.on_error("connection")
        finally:
            self._is_running = False

    async def close(self) -> None:
        async with self._close_lock:
            self._is_running = False
            if self._receive_task and not self._receive_task.done():
                self._receive_task.cancel()
                try:
                    await self._receive_task
                except asyncio.CancelledError:
                    pass
            self._receive_task = None
            async with self._send_lock:
                if self._ws:
                    try:
                        await self._ws.send(json.dumps({"type": "Terminate"}))
                    except Exception:
                        pass
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    self._ws = None
