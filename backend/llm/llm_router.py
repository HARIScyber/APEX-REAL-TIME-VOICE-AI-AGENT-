import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_CALL_DEPTH = 3
TOOL_TIMEOUT_SECONDS = 8.0


class LLMServiceError(Exception):
    """An error safe to present to a voice-agent user."""

    def __init__(self, message: str = "The language model is unavailable right now. Please try again.", stage: str = "llm"):
        super().__init__(message)
        self.stage = stage
        self.message = message


class LLMRouter:
    """Streams provider output and performs bounded, server-side tool calls."""

    def __init__(self, provider: str = "gemini", api_key: str = "", model_name: Optional[str] = None):
        self.provider = provider.lower().strip()
        self.api_key = api_key.strip()
        self.model_name = model_name or self._default_model(self.provider)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=4.0, read=12.0, write=5.0, pool=4.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self.last_tool_latency_ms = 0.0
        self.last_rag_latency_ms = 0.0

    @staticmethod
    def _default_model(provider: str) -> str:
        return {
            "openai": "gpt-4o-mini",
            "gemini": "gemini-2.5-flash",
            "anthropic": "claude-3-5-sonnet-20241022",
            "groq": "llama-3.3-70b-versatile",
            "mock": "simulated-voice-llm",
        }.get(provider, "gemini-2.5-flash")

    @staticmethod
    def _gemini_tools() -> List[Dict[str, Any]]:
        declarations = []
        for tool in ToolRegistry.get_definitions():
            function = tool.get("function", {})
            declarations.append(
                {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                }
            )
        return [{"functionDeclarations": declarations}]

    async def stream_response(
        self, messages: List[Dict[str, str]], tools_enabled: bool = True, depth: int = 0
    ) -> AsyncGenerator[str, None]:
        if depth == 0:
            self.last_tool_latency_ms = 0.0
            self.last_rag_latency_ms = 0.0
            logger.info("[LLM] provider=%s model=%s request_started", self.provider, self.model_name)
        if self.provider == "mock":
            async for token in self._mock_stream(messages):
                yield token
            return
        if not self.api_key:
            raise LLMServiceError(f"{self.provider.title()} API key is not configured.", stage="llm")
        if depth >= MAX_TOOL_CALL_DEPTH:
            tools_enabled = False

        t_start = time.perf_counter()
        first_token = True
        try:
            generator = (
                self._stream_gemini(messages, tools_enabled, depth)
                if self.provider == "gemini"
                else self._stream_openai_compatible(messages, tools_enabled, depth)
            )
            async for token in generator:
                if first_token and depth == 0:
                    first_token = False
                    logger.info("[LLM] first_chunk after %.1fms", (time.perf_counter() - t_start) * 1000)
                yield token
        except LLMServiceError:
            raise
        except (httpx.HTTPError, asyncio.TimeoutError) as error:
            logger.warning("LLM request failed for provider %s: %s", self.provider, type(error).__name__)
            raise LLMServiceError(f"LLM connection error ({self.provider}): {type(error).__name__}", stage="llm") from error

    async def _stream_gemini(
        self, messages: List[Dict[str, str]], tools_enabled: bool, depth: int
    ) -> AsyncGenerator[str, None]:
        system_instruction = None
        contents: List[Dict[str, Any]] = []
        for message in messages:
            if message["role"] == "system":
                system_instruction = {"parts": [{"text": message["content"]}]}
            else:
                contents.append(
                    {
                        "role": "model" if message["role"] == "assistant" else "user",
                        "parts": [{"text": message["content"]}],
                    }
                )

        # Build prioritized candidate model list to survive rate limits (429) and model deprecations (404)
        candidates = [self.model_name]
        for alt in ["gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-3-flash-preview"]:
            if alt not in candidates:
                candidates.append(alt)

        last_err = None
        for model in candidates:
            try:
                emitted_any = False
                async for token in self._stream_gemini_contents(
                    contents, system_instruction, tools_enabled, depth, target_model=model
                ):
                    emitted_any = True
                    yield token
                if emitted_any:
                    return
            except LLMServiceError as err:
                last_err = err
                logger.warning("[LLM] Model %s failed: %s. Trying next candidate model...", model, err)
                continue

        # If all Gemini models are exhausted or 429'd, attempt seamless failover to Groq if key configured
        from backend.config import config
        if config.groq_api_key and config.groq_api_key.strip():
            try:
                logger.info("[LLM] All Gemini models exhausted. Seamlessly failing over to Groq (%s)...", config.groq_model)
                orig_provider, orig_model, orig_key = self.provider, self.model_name, self.api_key
                self.provider = "groq"
                self.model_name = config.groq_model
                self.api_key = config.groq_api_key
                try:
                    async for token in self._stream_openai_compatible(messages, tools_enabled, depth):
                        yield token
                    return
                finally:
                    self.provider, self.model_name, self.api_key = orig_provider, orig_model, orig_key
            except Exception as groq_err:
                logger.warning("[LLM] Groq failover failed: %s", groq_err)

        if last_err:
            raise last_err
        raise LLMServiceError("All language model candidates are temporarily unavailable.", stage="llm")

    async def _stream_gemini_contents(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[Dict[str, Any]],
        tools_enabled: bool,
        depth: int,
        target_model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        model_to_use = target_model or self.model_name
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 350},
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if tools_enabled:
            payload["tools"] = self._gemini_tools()

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_use}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        function_calls: List[Dict[str, Any]] = []
        model_parts: List[Dict[str, Any]] = []

        max_retries = 2
        for attempt in range(max_retries):
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code == 429 and attempt < max_retries - 1:
                    logger.warning("[LLM] %s rate limited (429), retrying in 1.5s (attempt %s/%s)...", model_to_use, attempt + 1, max_retries)
                    await asyncio.sleep(1.5)
                    continue
                if response.status_code != 200:
                    body = await response.aread()
                    body_text = body.decode("utf-8", errors="replace")[:300]
                    if response.status_code == 404:
                        msg = f"Gemini model unavailable: {model_to_use}"
                        logger.error("%s. Body: %s", msg, body_text)
                        raise LLMServiceError(msg, stage="llm")
                    elif response.status_code in (401, 403):
                        msg = "Gemini authentication failed"
                        logger.error("%s (%s). Check GEMINI_API_KEY in .env.", msg, response.status_code)
                        raise LLMServiceError(msg, stage="llm")
                    else:
                        msg = f"Gemini model {model_to_use} failed (status {response.status_code})"
                        logger.warning("%s. Body: %s", msg, body_text)
                        raise LLMServiceError(msg, stage="llm")
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    candidate = next(iter(chunk.get("candidates", [])), {})

                    for part in candidate.get("content", {}).get("parts", []):
                        model_parts.append(part)
                        if part.get("text"):
                            yield part["text"]
                        if part.get("functionCall") and depth < MAX_TOOL_CALL_DEPTH:
                            function_calls.append(part["functionCall"])
                break

        if not function_calls or depth >= MAX_TOOL_CALL_DEPTH:
            return

        tool_responses = []
        for function_call in function_calls:
            result = await self._run_tool(function_call.get("name", ""), function_call.get("args", {}))
            response_part = {
                "name": function_call.get("name", ""),
                "response": {"result": result},
            }
            if function_call.get("id"):
                response_part["id"] = function_call["id"]
            tool_responses.append({"functionResponse": response_part})

        follow_up = list(contents)
        follow_up.append({"role": "model", "parts": model_parts or [{"text": ""}]})
        follow_up.append({"role": "user", "parts": tool_responses})
        async for token in self._stream_gemini_contents(follow_up, system_instruction, tools_enabled, depth + 1):
            yield token

    async def _stream_openai_compatible(
        self, messages: List[Dict[str, str]], tools_enabled: bool, depth: int
    ) -> AsyncGenerator[str, None]:
        base_url = "https://api.groq.com/openai/v1" if self.provider == "groq" else "https://api.openai.com/v1"
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "temperature": 0.4,
            "max_tokens": 350,
        }
        if tools_enabled:
            payload["tools"] = ToolRegistry.get_definitions()
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        calls: Dict[int, Dict[str, str]] = {}

        async with self._client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=payload) as response:
            if response.status_code != 200:
                logger.warning("%s request failed with status %s", self.provider, response.status_code)
                raise LLMServiceError()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line[6:] == "[DONE]":
                    continue
                try:
                    delta = json.loads(line[6:])["choices"][0].get("delta", {})
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
                if delta.get("content"):
                    yield delta["content"]
                for call in delta.get("tool_calls", []):
                    index = call.get("index", 0)
                    current = calls.setdefault(index, {"name": "", "arguments": "{}"})
                    function = call.get("function", {})
                    current["name"] = function.get("name", current["name"])
                    current["arguments"] += function.get("arguments", "")

        if not calls or depth >= MAX_TOOL_CALL_DEPTH:
            return
        follow_up = list(messages)
        for call in calls.values():
            try:
                arguments = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            result = await self._run_tool(call["name"], arguments)
            follow_up.append({"role": "user", "content": f"Tool result for {call['name']}: {result}"})
        async for token in self._stream_openai_compatible(follow_up, tools_enabled, depth + 1):
            yield token

    async def _run_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        try:
            result, latency_ms, is_rag = await asyncio.wait_for(
                asyncio.to_thread(ToolRegistry.execute_timed, name, arguments), timeout=TOOL_TIMEOUT_SECONDS
            )
            self.last_tool_latency_ms += latency_ms
            if is_rag:
                self.last_rag_latency_ms += latency_ms
            return result
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out", name)
            return "The requested lookup timed out."
        except Exception:
            logger.exception("Tool %s failed", name)
            return "The requested lookup could not be completed."

    async def _mock_stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        last_user_message = next((item["content"] for item in reversed(messages) if item["role"] == "user"), "")
        response = f"I heard you. Regarding {last_user_message}, how can I help further?"
        for word in response.split():
            yield f"{word} "
            await asyncio.sleep(0.03)

    async def check_health(self) -> Dict[str, Any]:
        """Check LLM provider configuration and model reachability."""
        if self.provider == "mock":
            return {
                "provider": "mock",
                "model": self.model_name,
                "configured": True,
                "reachable": True,
                "last_error": None,
                "mode": "mock",
            }
        if not self.api_key:
            return {
                "provider": self.provider,
                "model": self.model_name,
                "configured": False,
                "reachable": False,
                "last_error": f"{self.provider.title()} API key is not configured.",
            }
        try:
            if self.provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}?key={self.api_key}"
                resp = await self._client.get(url, timeout=4.0)
                if resp.status_code == 200:
                    return {
                        "provider": "gemini",
                        "model": self.model_name,
                        "configured": True,
                        "reachable": True,
                        "last_error": None,
                    }
                elif resp.status_code in (401, 403):
                    return {
                        "provider": "gemini",
                        "model": self.model_name,
                        "configured": True,
                        "reachable": False,
                        "last_error": "Gemini authentication failed",
                    }
                elif resp.status_code == 404:
                    return {
                        "provider": "gemini",
                        "model": self.model_name,
                        "configured": True,
                        "reachable": False,
                        "last_error": f"Gemini model unavailable: {self.model_name}",
                    }
                else:
                    return {
                        "provider": "gemini",
                        "model": self.model_name,
                        "configured": True,
                        "reachable": False,
                        "last_error": f"Gemini error (status {resp.status_code})",
                    }
            elif self.provider in {"openai", "groq"}:
                base_url = "https://api.groq.com/openai/v1" if self.provider == "groq" else "https://api.openai.com/v1"
                resp = await self._client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=4.0,
                )
                return {
                    "provider": self.provider,
                    "model": self.model_name,
                    "configured": True,
                    "reachable": resp.status_code == 200,
                    "last_error": None if resp.status_code == 200 else f"HTTP {resp.status_code}",
                }
            else:
                return {
                    "provider": self.provider,
                    "model": self.model_name,
                    "configured": True,
                    "reachable": False,
                    "last_error": f"Unsupported provider {self.provider}",
                }
        except Exception as e:
            return {
                "provider": self.provider,
                "model": self.model_name,
                "configured": True,
                "reachable": False,
                "last_error": str(e),
            }

    async def aclose(self) -> None:
        await self._client.aclose()
