# Apex Real-Time Voice AI Agent — Complete Development & Run Guide

This comprehensive guide explains every detail of the **Real-Time Voice AI Agent** codebase, how each module maps to the architecture workflow, how to run the project in multiple ways, and how to customize or extend it.

---

## 📑 Table of Contents
1. [Architecture Workflow Mapping](#1-architecture-workflow-mapping)
2. [Folder & File Directory Structure](#2-folder--file-directory-structure)
3. [Prerequisites](#3-prerequisites)
4. [How to Run the Project](#4-how-to-run-the-project)
   - [Method 1: Windows Batch File (`run.bat`)](#method-1-windows-batch-file-runbat)
   - [Method 2: PowerShell (`run.ps1`)](#method-2-powershell-runps1)
   - [Method 3: Standard Terminal / Manual](#method-3-standard-terminal--manual)
5. [Testing Modes: Zero-Key Dev Simulator vs. Real Cloud Models](#5-testing-modes)
6. [API Keys & Configuration](#6-api-keys--configuration)
7. [Deep Dive into Core Technical Mechanics](#7-deep-dive-into-core-technical-mechanics)
   - [Voice Activity Detection (VAD) & Turn Detection](#voice-activity-detection-vad--turn-detection)
   - [Barge-In (Interruption Handling)](#barge-in-interruption-handling)
   - [Sentence Boundary Chunking for Low Latency TTS](#sentence-boundary-chunking-for-low-latency-tts)
   - [Sub-Second Telemetry HUD](#sub-second-telemetry-hud)
8. [How to Add Custom Tools & Function Calling](#8-how-to-add-custom-tools--function-calling)
9. [How to Add New Personas](#9-how-to-add-new-personas)
10. [Production Deployment (Docker & Nginx)](#10-production-deployment)

---

## 1. Architecture Workflow Mapping

This project implements every single block from the architecture diagram:

```
[ User / Frontend ]
   │
   │  16kHz 16-bit PCM Audio Stream (WebSocket)
   ▼
[ Real-Time STT ] ──────────────► AssemblyAI Real-Time WebSocket API (v2)
                                   (Emits sub-second Partial & Final Transcripts)
   │
   ▼
[ Backend Orchestrator ] (Python / FastAPI)
   ├── Conversation Manager ─────► Turn Detection & Barge-in (Interruption Handling)
   ├── Intent & Routing ─────────► Persona Prompts & Policy Enforcement
   ├── State & Memory ───────────► Short-Term History + Long-Term User Attributes
   └── Audio Processing ────────► VAD (Voice Activity Detection) & Silence Thresholding
   │
   ├──► [ Tools & Capabilities ] ─► Enterprise RAG, Order SQL DB, Smart IoT Actions
   │
   ├──► [ Bring Your Own LLM ] ──► Gemini 2.0 Flash / OpenAI GPT-4o / Claude / Groq
   │     (Streams Tokens)
   │
   ▼
[ Text-to-Speech (TTS) ] ───────► ElevenLabs Streaming Turbo v2.5 / Browser Fallback
   │
   │  Synthesized Streaming Audio Chunks
   ▼
[ User Playback ] ──────────────► Web Audio API Player + Canvas Waveform Visualizer
```

---

## 2. Folder & File Directory Structure

```
realtime-voice-agent/
│
├── backend/                               # Python FastAPI Server & Orchestrator
│   ├── __init__.py                        # Package marker
│   ├── config.py                          # Settings, audio specs & environment variables
│   ├── main.py                            # FastAPI entry point, static mount, WebSocket route
│   │
│   ├── audio_processing/                  # Audio Signal Analysis
│   │   ├── __init__.py
│   │   └── vad.py                         # 16-bit PCM Voice Activity Detector (Decibels & RMS)
│   │
│   ├── orchestrator/                      # Conversational State & Coordination
│   │   ├── __init__.py
│   │   ├── conversation_manager.py        # Turn detection, barge-in logic, streaming coordinator
│   │   ├── intent_engine.py               # System prompts, personas, fast intent rules
│   │   └── state_memory.py                # Multi-turn chat buffer and user preferences
│   │
│   ├── stt/                               # Speech-to-Text Integration
│   │   ├── __init__.py
│   │   └── assemblyai_stt.py              # AssemblyAI WebSocket v2 streaming client
│   │
│   ├── llm/                               # Intelligence Layer (Bring Your Own LLM)
│   │   ├── __init__.py
│   │   └── llm_router.py                  # Multi-provider streaming router (Gemini, OpenAI, Claude, Groq, Mock)
│   │
│   ├── tools/                             # Actions, RAG & Database Capabilities
│   │   ├── __init__.py
│   │   └── registry.py                    # Mock database, RAG search, IoT device control
│   │
│   └── tts/                               # Speech Synthesis
│       ├── __init__.py
│       └── tts_service.py                 # ElevenLabs streaming TTS & sentence boundary chunker
│
├── frontend/                              # Futuristic Cyber-Glass Browser Interface
│   ├── index.html                         # Layout, Canvas visualizer, dual-stream chat, HUD
│   ├── css/
│   │   └── style.css                      # Cyberpunk dark mode styling, glowing neon elements
│   └── js/
│       ├── audio-processor.js             # Web Audio API 16kHz PCM recorder & queue player
│       └── app.js                         # WebSocket coordinator, Canvas visualizer, HUD
│
├── .env.example                           # Configuration & API keys template
├── requirements.txt                       # Minimal, robust Python dependencies
├── run.bat                                # Windows Command Prompt 1-click launcher
├── run.ps1                                # Windows PowerShell 1-click launcher
├── README.md                              # High-level overview
└── GUIDE.md                               # This comprehensive technical guide
```

---

## 3. Prerequisites

* **Operating System**: Windows 10/11, macOS, or Linux.
* **Python**: Python **3.10** or newer (Python 3.11 recommended). Verify by running:
  ```bash
  python --version
  ```
* **Hardware**: Microphone & speakers or headphones.

---

## 4. How to Run the Project

### Method 1: Windows Batch File (`run.bat`)
The easiest method on Windows:
1. Navigate to the project folder:
   ```
   C:\Users\ADMIN\.gemini\antigravity-ide\scratch\realtime-voice-agent
   ```
2. Double-click **`run.bat`**.
3. It will automatically create `.venv`, install packages from `requirements.txt`, and start Uvicorn on `http://localhost:8000`.
4. Open **http://localhost:8000** in your browser.

---

### Method 2: PowerShell (`run.ps1`)
1. Open PowerShell and navigate to the project directory:
   ```powershell
   cd C:\Users\ADMIN\.gemini\antigravity-ide\scratch\realtime-voice-agent
   ```
2. If PowerShell script execution is restricted, run:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```
3. Run the launcher:
   ```powershell
   .\run.ps1
   ```
4. Open **http://localhost:8000** in your browser.

---

### Method 3: Standard Terminal / Manual
1. Open any command line terminal in the project directory.
2. (Optional but recommended) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Launch the application with Uvicorn:
   ```bash
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```
5. Open **http://localhost:8000** in Google Chrome or Microsoft Edge.

---

## 5. Testing Modes

The application comes with **two operating modes**:

### Mode A: Zero-Key Dev Simulator (Default)
You can run and test **everything immediately** without creating accounts or entering credit cards:
- **Speech-to-Text**: If no AssemblyAI key is provided, the browser uses its native speech recognition or quick-prompt chips.
- **LLM**: The built-in responsive Dev Mock detects order queries, policy searches, or IoT commands and returns accurate tool answers with realistic word-by-word streaming delays (~40ms).
- **Voice Playback**: Uses browser Web Speech Synthesis (`window.speechSynthesis`) with zero setup.

### Mode B: Real Cloud Production Mode
Enter real API keys in `.env` or in the **Settings (⚙️)** modal in the top-right of the web page:
- **STT**: AssemblyAI Real-Time WebSocket v2 for sub-second transcription.
- **LLM**: Google Gemini 2.0 Flash, OpenAI GPT-4o-mini, Anthropic Claude 3.5, or Groq Llama 3.3.
- **TTS**: ElevenLabs Turbo v2.5 streaming voice.

---

## 6. API Keys & Configuration

To enable cloud services, copy `.env.example` to `.env`:
```bash
copy .env.example .env
```

Edit `.env` with your preferred keys:
```ini
# 1. Speech-to-Text (AssemblyAI)
# https://www.assemblyai.com/
ASSEMBLYAI_API_KEY=your_assemblyai_api_key_here

# 2. Text-to-Speech (ElevenLabs)
# https://elevenlabs.io/
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM  # Rachel (default)
ELEVENLABS_MODEL_ID=eleven_flash_v2_5

# 3. LLM Provider (openai | gemini | anthropic | groq | mock)
DEFAULT_LLM_PROVIDER=gemini

# Google Gemini (Recommended for speed): https://aistudio.google.com/
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.6-flash

# OpenAI: https://platform.openai.com/
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini

# Groq (Fastest Llama inference): https://console.groq.com/
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

> **Tip**: You can also enter or switch keys inside the web UI by clicking the **Settings (⚙️)** button at runtime without restarting the server!

---

## 7. Deep Dive into Core Technical Mechanics

### Voice Activity Detection (VAD) & Turn Detection
* File: `backend/audio_processing/vad.py`
* Converts incoming 16-bit binary PCM buffers into audio samples:
  $$\text{RMS} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} s_i^2}$$
  $$\text{dB} = 20 \log_{10}\left(\frac{\text{RMS}}{32768}\right)$$
* When energy exceeds `-40.0 dB`, speech is detected.
* VAD reports a confirmed speech end after the configured silence timeout; AssemblyAI's final transcript remains the authoritative trigger for an assistant response.

### Barge-In (Interruption Handling)
* Files: `backend/orchestrator/conversation_manager.py` & `frontend/js/audio-processor.js`
* If the assistant is generating or synthesizing speech and the user speaks:
  1. The backend increments `self.turn_counter += 1`, immediately causing active generation loops to exit.
  2. The backend sends `{"type": "interrupted", "reason": "speech_detected"}` to the frontend over WebSocket.
  3. The frontend `StreamingAudioPlayer.stopAndClear()` immediately stops `AudioBufferSourceNode`, empties the playback buffer queue, and cancels browser speech synthesis.

### Sentence Boundary Chunking for Low Latency TTS
* File: `backend/tts/tts_service.py`
* Rather than waiting for the entire LLM response (which might take 3–5 seconds), `TextChunker` inspects incoming tokens for punctuation marks (`.`, `?`, `!`, `,`, `;`).
* As soon as a complete sentence or clause with at least 3 words is formed, it is dispatched to ElevenLabs immediately. The user hears the first spoken sentence in ~300ms while the LLM is still finishing the rest of the text.

### Sub-Second Telemetry HUD
* Bottom bar in `frontend/index.html`:
  * **STT Mode**: Shows whether AssemblyAI or WebRTC fallback is active.
  * **LLM TTFT**: Time-To-First-Token in milliseconds.
  * **TTFA**: Time-To-First-Audio synthesized.
  * **Turn Roundtrip**: Total elapsed turn latency.

---

## 8. How to Add Custom Tools & Function Calling

All tools are centralized in `backend/tools/registry.py`. To add a new tool:

1. Add your execution method to `ToolRegistry`:
   ```python
   @staticmethod
   def get_weather(city: str) -> str:
       # Replace with your actual API call or database query
       return f"The current weather in {city} is 72°F and sunny with mild humidity."
   ```

2. Add its schema to `get_definitions()`:
   ```python
   {
       "type": "function",
       "function": {
           "name": "get_weather",
           "description": "Get current weather conditions for a given city.",
           "parameters": {
               "type": "object",
               "properties": {
                   "city": {"type": "string", "description": "The city name"}
               },
               "required": ["city"]
           }
       }
   }
   ```

3. Route it in `execute()`:
   ```python
   elif name == "get_weather":
       return cls.get_weather(args.get("city", ""))
   ```

---

## 9. How to Add New Personas

Personas are defined in `backend/orchestrator/intent_engine.py`. To add a new persona (e.g. `financial_advisor`):

1. Add a prompt template to `PERSONA_PROMPTS`:
   ```python
   "financial_advisor": (
       "You are Sterling, a certified financial planning assistant. "
       "Provide prudent, structured insights on savings and investments. "
       "Keep your answers spoken, concise (2-3 sentences), and do not use markdown asterisks or bullet points."
   )
   ```

2. Add the option to `frontend/index.html` inside `<select id="personaSelect">`:
   ```html
   <option value="financial_advisor">Financial Advisor</option>
   ```

---

## 10. Production Deployment

### Docker Deployment
Create a `Dockerfile` in the root folder:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
Build and run:
```bash
docker build -t realtime-voice-agent .
docker run -p 8000:8000 --env-file .env realtime-voice-agent
```

### Nginx Reverse Proxy Configuration
To enable HTTPS and secure WebSocket (`wss://`):
```nginx
server {
    listen 443 ssl http2;
    server_name voice.yourdomain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```
