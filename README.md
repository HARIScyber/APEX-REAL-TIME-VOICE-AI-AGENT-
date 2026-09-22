# Real-Time Voice AI Agent — End-to-End Orchestrator

An enterprise-grade, sub-second real-time conversational voice agent built with **AssemblyAI Real-Time Speech-to-Text WebSocket API**, **Custom Python/FastAPI Orchestration**, **Multi-Provider LLM Streaming**, **Tool Calling & RAG**, **Streaming TTS (ElevenLabs)**, and a **Futuristic Glassmorphism Web Interface** with live audio visualizer and barge-in (interruption) handling.

---

## 🏛️ System Architecture

```
                                  +------------------------------------------------+
                                  |         BACKEND ORCHESTRATOR (FastAPI)         |
                                  |                                                |
[ USER / CLIENT ]                 |  [Conversation Manager]                        |               [ LLM (Bring Your Own) ]
+----------------+                |  - Session Management                          |               +----------------------+
| Microphone In  |                |  - Context & Memory                            |               | - Google Gemini      |
| (16kHz PCM)    | ---> [WS] ---> |  - Turn Detection                              | <===========> | - OpenAI GPT-4o-mini |
| Audio Playback | <--- [WS] <--- |  - Interruption Handling (Barge-In)            |  Token Stream | - Claude 3.5 Sonnet  |
+----------------+                |                         |                      |               | - Groq (Llama 3.3)   |
                                  |                         v                      |               +----------------------+
                                  |  [Intent & Orchestration Engine]               |                          ^
                                  |  - Policy / Rules                              |                          |
                                  |  - Route to Tools / LLM                        |                          v
                                  |                         |                      |               [ TOOLS & CAPABILITIES ]
                                  |                         v                      |               +----------------------+
                                  |  [State Management & Memory]                   |               | - RAG Knowledge Base |
                                  |  - Short-Term Chat History                     |               | - Database / SQL     |
                                  |  - Long-Term User Preferences                  |               | - IoT / Smart Home   |
                                  +------------------------------------------------+               +----------------------+
                                          |                                |
                                          v                                v
                          +-------------------------------+   +-----------------------------+
                          |   REAL-TIME SPEECH-TO-TEXT    |   |     TEXT-TO-SPEECH (TTS)    |
                          |   AssemblyAI WebSocket v2     |   |   ElevenLabs Streaming API  |
                          |   - Sub-second transcription  |   |   - Turbo v2.5 synthesis    |
                          |   - Partial & final events    |   |   - Browser TTS fallback    |
                          +-------------------------------+   +-----------------------------+
```

---

## 🚀 Key Features

1. **Sub-Second Real-Time STT (AssemblyAI v2)**:
   * Direct WebSocket streaming of 16kHz 16-bit linear PCM audio.
   * Delivers live partial transcripts as the user speaks, followed by punctuated final transcripts.
2. **True Barge-In (Interruption Handling)**:
   * When the user starts speaking while the assistant is talking, the orchestrator immediately cancels active LLM generation tasks and sends a flush signal to the frontend to instantly stop audio playback.
3. **Bring-Your-Own-LLM (BYO-LLM)**:
   * **Google Gemini** (`gemini-3.6-flash`)
   * **OpenAI** (`gpt-4o`, `gpt-4o-mini`)
   * **Anthropic** (`claude-3-5-sonnet-20241022`, `claude-3-haiku`)
   * **Groq** (`llama-3.3-70b-versatile`) for ultra-low latency inference.
   * **Responsive Dev Mock Engine**: Included out-of-the-box so you can test everything immediately without incurring cloud API costs!
4. **Tool Calling & Enterprise RAG**:
   * Order lookup database query (`ORD-1001`, `ORD-1002`, `ORD-1003`).
   * Enterprise Knowledge Base search for return policies, warranty, and customer support.
   * Smart home IoT controller for lights and thermostat.
5. **Low-Latency Streaming TTS**:
   * Uses ElevenLabs Turbo v2.5 streaming or seamless browser speech synthesis fallback.
   * Integrated sentence boundary chunker to stream audio without waiting for the full LLM response.
6. **Futuristic Visual Interface**:
   * HTML5 Canvas audio waveform and glowing orb that pulses dynamically with voice volume.
   * Real-time Performance HUD: STT latency, LLM Time-to-First-Token (TTFT), First Audio (TTFA), and Roundtrip latency.
   * Dynamic Settings drawer to configure API keys on the fly.

---

## 📦 Project Structure

```
realtime-voice-agent/
├── backend/
│   ├── __init__.py
│   ├── config.py                 # Configuration & environment loader
│   ├── main.py                   # FastAPI server, static mount, WebSocket endpoint
│   ├── audio_processing/
│   │   ├── __init__.py
│   │   └── vad.py                # 16-bit PCM Voice Activity Detector
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── conversation_manager.py # Turn detection, barge-in, streaming orchestration
│   │   ├── intent_engine.py      # Persona prompts, rules, intent routing
│   │   └── state_memory.py       # Short-term chat buffer & user preferences
│   ├── stt/
│   │   ├── __init__.py
│   │   └── assemblyai_stt.py     # AssemblyAI Real-Time WebSocket client
│   ├── llm/
│   │   ├── __init__.py
│   │   └── llm_router.py         # Multi-provider streaming client (Gemini, OpenAI, etc.)
│   ├── tools/
│   │   ├── __init__.py
│   │   └── registry.py           # Knowledge base RAG, order DB, and action tools
│   └── tts/
│       ├── __init__.py
│       └── tts_service.py        # ElevenLabs streaming TTS & sentence chunker
├── frontend/
│   ├── index.html                # Modern cyberpunk/glassmorphism UI
│   ├── css/
│   │   └── style.css             # Fluid layout, glowing neon accents, animations
│   └── js/
│       ├── audio-processor.js    # PCM 16kHz audio recorder & streaming player
│       └── app.js                # WebSocket coordinator & Canvas visualizer
├── .env.example                  # Template for API keys
├── requirements.txt              # Python dependencies
├── run.bat                       # One-click Windows starter script
├── run.ps1                       # PowerShell launcher
└── README.md                     # Documentation & setup guide
```

---

## 🛠️ Quickstart Installation & Running

### Step 1: Install Dependencies
Open PowerShell or Command Prompt in this folder:

```bash
# Optional: create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### Step 2: Configure API Keys (Optional)
Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```
Add any API keys you wish to use:
* `ASSEMBLYAI_API_KEY`: Get your free key at [AssemblyAI](https://www.assemblyai.com/).
* `GEMINI_API_KEY`: Get from [Google AI Studio](https://aistudio.google.com/).
* `OPENAI_API_KEY` or `GROQ_API_KEY`: For OpenAI or ultra-fast Groq Llama models.
* `ELEVENLABS_API_KEY`: Get from [ElevenLabs](https://elevenlabs.io/).

> **Note**: You can also enter or change your keys directly in the web UI using the gear icon ⚙️ at any time, or run with the built-in **Responsive Dev Mock** engine for zero-cost immediate testing!

### Step 3: Run the Server
Double-click `run.bat` or run:
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 4: Open in Browser
Navigate to:
```
http://localhost:8000
```
1. Allow microphone permissions when prompted.
2. Click the central glowing **Microphone Button** (or hold **Spacebar**) and speak.
3. Observe real-time transcript streaming, tool actions, and voice playback!
