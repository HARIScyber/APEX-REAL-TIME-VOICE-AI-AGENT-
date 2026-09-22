import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from backend.llm.llm_router import LLMRouter

async def test_all():
    candidates = [
        ("gemini", "gemini-2.5-flash", os.getenv("GEMINI_API_KEY")),
        ("gemini", "gemini-2.0-flash", os.getenv("GEMINI_API_KEY")),
        ("gemini", "gemini-1.5-flash", os.getenv("GEMINI_API_KEY")),
        ("groq", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), os.getenv("GROQ_API_KEY")),
        ("openai", os.getenv("OPENAI_MODEL", "gpt-4o-mini"), os.getenv("OPENAI_API_KEY")),
    ]
    for prov, model, key in candidates:
        if not key or "your_" in key:
            print(f"[SKIP] {prov} {model}: no key")
            continue
        try:
            r = LLMRouter(provider=prov, api_key=key, model_name=model)
            tokens = []
            async for t in r.stream_response([{"role": "user", "content": "Hello in 3 words"}], tools_enabled=False):
                tokens.append(t)
            full = "".join(tokens).strip()
            print(f"[OK] {prov} {model}: {full!r}")
            await r.aclose()
        except Exception as e:
            print(f"[FAIL] {prov} {model}: {e}")

if __name__ == "__main__":
    asyncio.run(test_all())
