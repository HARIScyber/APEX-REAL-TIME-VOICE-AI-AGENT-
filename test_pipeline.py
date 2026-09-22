"""
================================================================================
APEX VOICE AGENT — AUTOMATED SMOKE TEST
================================================================================
Tests the full pipeline without microphone:
  1. Config loads correctly
  2. Gemini LLM health check
  3. Text → LLM → streaming response (3 test prompts)
  4. LLM → TTS → audio chunk produced
  5. Tool calling works (order lookup)
  6. TextChunker produces sentence chunks

Run with:
    .venv\Scripts\python.exe test_pipeline.py

Expected output: All tests PASS with timing metrics.
================================================================================
"""

import asyncio
import sys
import time

# Ensure stdout and stderr use UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def log(msg: str, level: str = "INFO"):
    prefix = {
        "PASS": "[PASS]",
        "FAIL": "[FAIL]",
        "INFO": "[INFO]",
        "WARN": "[WARN]",
    }.get(level, "      ")
    print(f"  {prefix}  {msg}")


async def run_tests():
    total_tests = 0
    passed_tests = 0

    print()
    print("=" * 65)
    print("  APEX VOICE AGENT — PIPELINE SMOKE TEST")
    print("=" * 65)

    # ── TEST 1: Config loads ────────────────────────────────────────────────
    print("\n[1] Configuration")
    total_tests += 1
    try:
        from backend.config import config
        assert config.default_llm_provider, "default_llm_provider is empty"
        assert config.assemblyai_api_key, "ASSEMBLYAI_API_KEY not set"
        assert config.gemini_api_key, "GEMINI_API_KEY not set"
        assert config.elevenlabs_api_key, "ELEVENLABS_API_KEY not set"
        log(f"provider={config.default_llm_provider} model={config.gemini_model}", "PASS")
        passed_tests += 1
    except Exception as exc:
        log(f"Config error: {exc}", "FAIL")

    # ── TEST 2: Gemini LLM health check ────────────────────────────────────
    print("\n[2] Gemini LLM Health Check")
    total_tests += 1
    try:
        from backend.llm.llm_router import LLMRouter
        router = LLMRouter(
            provider="gemini",
            api_key=config.gemini_api_key,
            model_name=config.gemini_model,
        )
        health = await router.check_health()
        assert health["reachable"], f"Gemini not reachable: {health.get('last_error')}"
        log(f"provider=gemini model={health['model']} reachable=True", "PASS")
        passed_tests += 1
        await router.aclose()
    except Exception as exc:
        log(f"LLM health check failed: {exc}", "FAIL")

    # ── TEST 3: LLM Streaming — 3 prompts ──────────────────────────────────
    print("\n[3] LLM Streaming Responses")
    test_prompts = [
        "What is artificial intelligence? Answer in one sentence.",
        "Explain machine learning in one sentence.",
        "What is the status of order ORD-1001?",
    ]

    for i, prompt in enumerate(test_prompts):
        total_tests += 1
        try:
            from backend.llm.llm_router import LLMRouter
            router = LLMRouter(
                provider="gemini",
                api_key=config.gemini_api_key,
                model_name=config.gemini_model,
            )
            messages = [
                {"role": "system", "content": "You are a helpful assistant. Be very brief."},
                {"role": "user", "content": prompt},
            ]
            t0 = time.perf_counter()
            tokens = []
            first_token_ms = None
            async for token in router.stream_response(messages, tools_enabled=(i == 2)):
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - t0) * 1000, 0)
                tokens.append(token)
            total_ms = round((time.perf_counter() - t0) * 1000, 0)
            response = "".join(tokens).strip()
            assert response, "Empty LLM response"
            assert len(response) > 5, f"Response too short: {response!r}"
            log(
                f"Prompt {i+1}: ttft={first_token_ms}ms total={total_ms}ms "
                f"chars={len(response)} preview={response[:60]!r}",
                "PASS",
            )
            passed_tests += 1
            await router.aclose()
            await asyncio.sleep(1.0)
        except Exception as exc:
            log(f"Prompt {i+1} failed: {exc}", "FAIL")

    # ── TEST 4: TTS audio generation ───────────────────────────────────────
    print("\n[4] ElevenLabs TTS Audio Generation")
    total_tests += 1
    try:
        from backend.tts.tts_service import TTSService
        tts = TTSService(
            api_key=config.elevenlabs_api_key,
            voice_id=config.elevenlabs_voice_id,
            model_id=config.elevenlabs_model_id,
        )
        t0 = time.perf_counter()
        chunks = []
        first_chunk_ms = None
        async for chunk in tts.stream_audio("Hello, this is a voice agent test."):
            if first_chunk_ms is None:
                first_chunk_ms = round((time.perf_counter() - t0) * 1000, 0)
            chunks.append(chunk)
        total_bytes = sum(len(c) for c in chunks)
        assert chunks, "No audio chunks received from ElevenLabs"
        assert total_bytes > 0, "Zero bytes received"
        duration_ms = round(total_bytes / 2 / 16000 * 1000, 0)
        # Verify all chunks have even byte count (correct PCM alignment)
        for j, chunk in enumerate(chunks):
            assert len(chunk) % 2 == 0, f"Chunk {j} has odd byte length: {len(chunk)}"
        log(
            f"chunks={len(chunks)} bytes={total_bytes} duration={duration_ms}ms "
            f"first_chunk={first_chunk_ms}ms format=pcm_s16le_16000",
            "PASS",
        )
        passed_tests += 1
        await tts.aclose()
    except Exception as exc:
        log(f"TTS test failed: {exc}", "FAIL")

    # ── TEST 5: TextChunker sentence splitting ──────────────────────────────
    print("\n[5] TextChunker Sentence Splitting")
    total_tests += 1
    try:
        from backend.tts.tts_service import TextChunker
        chunker = TextChunker(min_chunk_words=3)
        tokens = ["Hello ", "there. ", "This ", "is ", "a ", "test. ", "How ", "are ", "you ", "doing ", "today?"]
        chunks_out = []
        for token in tokens:
            result = chunker.add_token(token)
            if result:
                chunks_out.append(result)
        remaining = chunker.flush()
        if remaining:
            chunks_out.append(remaining)
        assert len(chunks_out) >= 2, f"Expected at least 2 chunks, got: {chunks_out}"
        log(f"chunks={chunks_out}", "PASS")
        passed_tests += 1
    except Exception as exc:
        log(f"TextChunker test failed: {exc}", "FAIL")

    # ── TEST 6: PersonaPlex hardware status ─────────────────────────────────
    print("\n[6] PersonaPlex Hardware Status")
    total_tests += 1
    try:
        from backend.personaplex import get_personaplex_service
        svc = get_personaplex_service()
        diag = svc.get_diagnostics()
        if diag["is_hardware_supported"]:
            log(f"GPU={diag['gpu_name']} VRAM={diag['gpu_memory_gb']}GB — hardware OK", "PASS")
        else:
            log(f"GPU unavailable — {diag['hardware_message'][:80]} (expected on CPU-only machine)", "PASS")
        passed_tests += 1
    except Exception as exc:
        log(f"PersonaPlex check failed: {exc}", "FAIL")

    # ── TEST 7: Tool calling (order lookup) ─────────────────────────────────
    print("\n[7] Tool Calling — Order Lookup")
    total_tests += 1
    try:
        from backend.tools.registry import ToolRegistry
        result, latency_ms, is_rag = ToolRegistry.execute_timed("lookup_order_status", {"order_id": "ORD-1001"})
        assert "ORD-1001" in result, f"Expected ORD-1001 in result: {result}"
        assert "Out for Delivery" in result, f"Expected status in result: {result}"
        log(f"result_preview={result[:80]!r} latency={latency_ms}ms", "PASS")
        passed_tests += 1
    except Exception as exc:
        log(f"Tool calling test failed: {exc}", "FAIL")

    # ── SUMMARY ────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    result_icon = "[SUCCESS]" if passed_tests == total_tests else "[WARNING]"
    print(f"  {result_icon} RESULTS: {passed_tests}/{total_tests} tests passed")
    print("=" * 65)
    print()

    if passed_tests < total_tests:
        failed = total_tests - passed_tests
        print(f"  [FAIL] {failed} test(s) failed - check output above for details.")
        print()
        sys.exit(1)
    else:
        print("  [SUCCESS] All tests passed! Pipeline is ready.")
        print("  Start the server with:  .venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload")
        print()


if __name__ == "__main__":
    asyncio.run(run_tests())
