/**
 * APEX REAL-TIME VOICE AI AGENT - MAIN FRONTEND APPLICATION
 *
 * FIX LOG:
 *  - BUG 1 FIXED: localStorage apex_model=mock was sent via syncSettingsWithBackend()
 *    on every WS open, silently overriding Gemini. Now: localStorage is cleared of
 *    any stale 'mock' value on load; initial WS connect does NOT send llm_provider.
 *    Only explicit user dropdown changes send llm_provider to the backend.
 *  - Added real LLM health check via /api/llm/health on page load.
 *  - Added diagnostics panel showing real subsystem status.
 *  - Mock mode now clearly labeled "⚠️ DEV MOCK" in UI.
 *  - Frontend state machine updated: READY/LISTENING/TRANSCRIBING/THINKING/SPEAKING/ERROR.
 */

document.addEventListener("DOMContentLoaded", () => {
  // ── DOM Elements ────────────────────────────────────────────────────────────
  const wsStatus = document.getElementById("wsStatus");
  const btnMic = document.getElementById("btnMic");
  const agentStateLabel = document.getElementById("agentStateLabel");
  const stateText = document.getElementById("stateText");
  const bargeinBadge = document.getElementById("bargeinBadge");
  const orbCenter = document.getElementById("orbCenter");
  const canvas = document.getElementById("waveformCanvas");
  const chatStream = document.getElementById("chatStream");
  const livePartialBar = document.getElementById("livePartialBar");
  const partialTranscriptText = document.getElementById("partialTranscriptText");
  const btnClearChat = document.getElementById("btnClearChat");
  const personaSelect = document.getElementById("personaSelect");
  const modelSelect = document.getElementById("modelSelect");

  // HUD & Telemetry
  const hudSTTMode = document.getElementById("hudSTTMode");
  const hudActiveEngine = document.getElementById("hudActiveEngine");
  const hudTTFT = document.getElementById("hudTTFT");
  const hudTTFA = document.getElementById("hudTTFA");
  const hudTotalTurn = document.getElementById("hudTotalTurn");
  const hudSTTLatency = document.getElementById("hudSTTLatency");
  const hudGenerationTotal = document.getElementById("hudGenerationTotal");
  const hudToolLatency = document.getElementById("hudToolLatency");
  const hudPPLoad = document.getElementById("hudPPLoad");
  const hudPPInference = document.getElementById("hudPPInference");
  const hudPPTTFA = document.getElementById("hudPPTTFA");
  const hudPPTotal = document.getElementById("hudPPTotal");
  const hudPPStatus = document.getElementById("hudPPStatus");
  const engineSelect = document.getElementById("engineSelect");

  // Diagnostics panel elements (new)
  const diagSttStatus = document.getElementById("diagSttStatus");
  const diagLlmStatus = document.getElementById("diagLlmStatus");
  const diagTtsStatus = document.getElementById("diagTtsStatus");
  const diagTurnId = document.getElementById("diagTurnId");
  const diagLastTranscript = document.getElementById("diagLastTranscript");

  // Settings Modal Elements
  const btnOpenSettings = document.getElementById("btnOpenSettings");
  const btnCloseSettings = document.getElementById("btnCloseSettings");
  const btnSaveSettings = document.getElementById("btnSaveSettings");
  const settingsModal = document.getElementById("settingsModal");
  const ttsVoiceSelect = document.getElementById("ttsVoiceSelect");

  // ── Application State ────────────────────────────────────────────────────────
  let ws = null;
  let isRecording = false;
  let isSpacePressed = false;
  let currentVolume = 0;
  let activeAssistantBubble = null;
  let activeTurnId = null;
  let speechSynthVoices = [];
  let lastAppendedUserText = "";
  let lastAppendedTime = 0;
  let fallbackQueue = [];
  let fallbackSpeaking = false;
  let fallbackGeneration = 0;
  // Track whether the user has explicitly changed the LLM provider this session
  let userExplicitlyChangedLlm = false;

  // ── Canvas Visualizer ────────────────────────────────────────────────────────
  const ctx = canvas.getContext("2d");
  function resizeCanvas() {
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = canvas.parentElement.clientHeight;
  }
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  // ── Speech Synthesis Voices (browser fallback) ───────────────────────────────
  function populateVoices() {
    if (!window.speechSynthesis) return;
    speechSynthVoices = window.speechSynthesis.getVoices();
    ttsVoiceSelect.innerHTML = '<option value="">Default System Voice</option>';
    speechSynthVoices.forEach((voice, index) => {
      const option = document.createElement("option");
      option.value = index;
      option.textContent = `${voice.name} (${voice.lang})`;
      ttsVoiceSelect.appendChild(option);
    });
  }
  if (window.speechSynthesis) {
    populateVoices();
    window.speechSynthesis.onvoiceschanged = populateVoices;
  }

  // ── Settings Load ─────────────────────────────────────────────────────────────
  // BUG FIX: Always clear any stale API key entries and the model selection.
  // If a user previously selected "mock" and closed the tab, we do NOT restore
  // that selection — the server's DEFAULT_LLM_PROVIDER (gemini) takes precedence.
  function loadSavedSettings() {
    // Security: remove any keys that should never be in localStorage
    ["apex_assemblyai_key", "apex_elevenlabs_key", "apex_llm_key"].forEach((k) =>
      localStorage.removeItem(k)
    );

    // BUG FIX: Never restore a stale 'mock' LLM selection automatically.
    // The default server config is gemini. Only restore if explicitly saved as non-mock.
    const savedModel = localStorage.getItem("apex_model");
    if (savedModel && savedModel !== "mock") {
      modelSelect.value = savedModel;
    } else {
      // Reset to gemini (server default) and clear stale mock entry
      modelSelect.value = "gemini";
      localStorage.removeItem("apex_model");
    }

    const savedPersona = localStorage.getItem("apex_persona");
    if (savedPersona) personaSelect.value = savedPersona;

    const savedEngine = localStorage.getItem("apex_engine");
    if (savedEngine && engineSelect) engineSelect.value = savedEngine;
  }
  loadSavedSettings();
  updateModelSelectLabel();

  // ── Health Check on Load ──────────────────────────────────────────────────────
  // Fetch real subsystem health from backend and display in diagnostics panel
  function fetchAndDisplayHealth() {
    fetch("/api/health")
      .then((r) => r.json())
      .then((data) => {
        if (data.personaplex && hudPPStatus) {
          hudPPStatus.textContent = data.personaplex.hardware_message || "Checked";
        }
        // Update diagnostics
        if (diagSttStatus) {
          diagSttStatus.textContent = data.assemblyai_configured ? "✅ Configured" : "❌ Not configured";
          diagSttStatus.className = data.assemblyai_configured ? "diag-ok" : "diag-error";
        }
      })
      .catch(() => {
        if (diagSttStatus) diagSttStatus.textContent = "⚠️ Health check failed";
      });

    // BUG FIX: Fetch real LLM status — do not rely on UI selector alone
    fetch("/api/llm/health")
      .then((r) => r.json())
      .then((data) => {
        if (diagLlmStatus) {
          if (data.reachable) {
            diagLlmStatus.textContent = `✅ ${data.provider} / ${data.model}`;
            diagLlmStatus.className = "diag-ok";
          } else {
            diagLlmStatus.textContent = `❌ ${data.provider}: ${data.last_error || "unreachable"}`;
            diagLlmStatus.className = "diag-error";
          }
          // Sync the dropdown to show what server is actually using
          if (data.provider && !userExplicitlyChangedLlm) {
            modelSelect.value = data.provider;
            updateModelSelectLabel();
          }
        }
      })
      .catch(() => {
        if (diagLlmStatus) diagLlmStatus.textContent = "⚠️ LLM health check failed";
      });

    fetch("/api/tts/health")
      .then((r) => r.json())
      .then((data) => {
        if (diagTtsStatus) {
          diagTtsStatus.textContent = data.configured ? "✅ ElevenLabs configured" : "❌ Not configured";
          diagTtsStatus.className = data.configured ? "diag-ok" : "diag-error";
        }
      })
      .catch(() => {
        if (diagTtsStatus) diagTtsStatus.textContent = "⚠️ TTS health check failed";
      });
  }
  fetchAndDisplayHealth();

  // ── Mock Mode Warning Label ────────────────────────────────────────────────────
  function updateModelSelectLabel() {
    const mockWarning = document.getElementById("mockModeWarning");
    if (modelSelect.value === "mock") {
      if (mockWarning) mockWarning.style.display = "inline";
    } else {
      if (mockWarning) mockWarning.style.display = "none";
    }
  }

  // ── Audio Components ──────────────────────────────────────────────────────────
  const audioPlayer = new StreamingAudioPlayer({
    onVolumeChange: (vol) => {
      currentVolume = vol * 1.5;
    },
    onPlaybackStateChange: (isPlaying) => {
      if (isPlaying) {
        setAgentState("speaking", "🔊 Speaking");
      } else if (isRecording) {
        setAgentState("listening", "🎤 Listening");
      } else {
        setAgentState("ready", "Ready to Listen");
      }
    },
  });

  const audioRecorder = new AudioStreamRecorder({
    sampleRate: 16000,
    onAudioData: (buffer) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(buffer);
      }
    },
    onVolumeChange: (vol) => {
      if (isRecording) {
        currentVolume = Math.min(1, vol * 6);
      }
    },
  });

  // ── WebSocket Connection ───────────────────────────────────────────────────────
  function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/voice`;

    setWsStatus("connecting", "Connecting");
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      setWsStatus("connected", "Connected");
      console.log("[WS] Connected to Voice Agent Orchestrator.");

      // BUG FIX: On initial connect, do NOT send llm_provider.
      // The server uses DEFAULT_LLM_PROVIDER from .env (gemini).
      // Only send persona and engine settings — not LLM provider — unless
      // the user explicitly changed it in this session.
      syncSettingsWithBackend({ includeLlmProvider: userExplicitlyChangedLlm });

      // Refresh health display after connection
      setTimeout(fetchAndDisplayHealth, 500);
    };

    ws.onclose = () => {
      setWsStatus("connecting", "Reconnecting...");
      setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = (err) => {
      console.error("[WS] WebSocket Error:", err);
      setWsStatus("error", "Error");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerEvent(data);
      } catch (e) {
        console.warn("[WS] Error parsing JSON message:", e);
      }
    };
  }

  // ── Server Event Handler ──────────────────────────────────────────────────────
  function handleServerEvent(data) {
    switch (data.type) {
      case "status":
        console.log("[Status]", data.message);
        if (data.stt_active !== undefined) {
          if (hudSTTMode) hudSTTMode.textContent = data.stt_active ? "AssemblyAI Live" : "Browser / WebRTC";
          if (diagSttStatus) {
            diagSttStatus.textContent = data.stt_active ? "✅ Connected" : "⚠️ Not connected";
            diagSttStatus.className = data.stt_active ? "diag-ok" : "diag-warn";
          }
        }
        break;

      case "partial_transcript":
        partialTranscriptText.textContent = `"${data.text}"`;
        livePartialBar.classList.add("active");
        if (diagLastTranscript) diagLastTranscript.textContent = `"${data.text}"`;
        setAgentState("transcribing", "📝 Transcribing");
        break;

      case "final_transcript":
        partialTranscriptText.textContent = "Processing…";
        livePartialBar.classList.remove("active");
        appendUserMessage(data.text);
        if (diagLastTranscript) diagLastTranscript.textContent = `✓ "${data.text}"`;
        if (diagTurnId) diagTurnId.textContent = data.turn_id || "—";
        setAgentState("thinking", "🧠 Thinking");
        break;

      case "assistant_start":
        activeTurnId = data.turn_id;
        if (diagTurnId) diagTurnId.textContent = activeTurnId;
        audioPlayer.beginTurn(activeTurnId);
        resetBrowserTTS();
        activeAssistantBubble = appendAssistantMessagePlaceholder(activeTurnId);
        setAgentState("thinking", "🧠 Thinking");
        break;

      case "assistant_token":
        if (activeAssistantBubble && data.turn_id === activeTurnId) {
          activeAssistantBubble.textContent += data.token;
          chatStream.scrollTop = chatStream.scrollHeight;
        }
        break;

      case "audio_chunk":
        // turn_id scoping is enforced inside enqueuePcmChunk
        audioPlayer.enqueuePcmChunk(data.audio, data.turn_id, data.sample_rate || 16000);
        break;

      case "tts_fallback":
        if (window.speechSynthesis && data.text && data.turn_id === activeTurnId) {
          enqueueBrowserTTS(data.text, data.turn_id);
        }
        break;

      case "turn_complete":
        if (data.metrics) {
          if (hudTTFT) hudTTFT.textContent = `${data.metrics.ttft_ms} ms`;
          if (hudTTFA) hudTTFA.textContent = `${data.metrics.tts_ttfa_ms} ms`;
          if (hudTotalTurn) hudTotalTurn.textContent = `${data.metrics.total_ms} ms`;
          if (hudSTTLatency)
            hudSTTLatency.textContent = `${data.metrics.stt_latency_ms} / ${data.metrics.turn_detection_ms} ms`;
          if (hudGenerationTotal)
            hudGenerationTotal.textContent = `${data.metrics.llm_total_ms} / ${data.metrics.tts_total_ms} ms`;
          if (hudToolLatency)
            hudToolLatency.textContent = `${data.metrics.tool_latency_ms} / ${data.metrics.rag_latency_ms} ms`;

          // PersonaPlex comparative metrics
          if (hudPPLoad) hudPPLoad.textContent = `${data.metrics.personaplex_load_ms || 0} ms`;
          if (hudPPInference) hudPPInference.textContent = `${data.metrics.personaplex_inference_ms || 0} ms`;
          if (hudPPTTFA) hudPPTTFA.textContent = `${data.metrics.personaplex_ttfa_ms || 0} ms`;
          if (hudPPTotal) hudPPTotal.textContent = `${data.metrics.personaplex_total_ms || 0} ms`;
          if (hudPPStatus) {
            hudPPStatus.textContent = data.fallback_active
              ? `Fallback: ${data.metrics.personaplex_status || "Unavailable"}`
              : data.engine === "personaplex"
              ? "Active"
              : data.metrics.personaplex_hardware || "Unavailable — CUDA GPU required";
          }
          if (hudActiveEngine) {
            hudActiveEngine.textContent = data.fallback_active
              ? "AssemblyAI (PP Fallback)"
              : data.engine === "personaplex"
              ? "NVIDIA PersonaPlex"
              : "AssemblyAI + Gemini";
          }
        }
        break;

      case "interrupted":
        console.log("[Interruption Event]", data.reason);
        audioPlayer.stopAndClear();
        resetBrowserTTS();
        activeTurnId = null;
        if (diagTurnId) diagTurnId.textContent = "—";
        flashBargeinIndicator();
        setAgentState("interrupted", "⏹ Interrupted");
        if (isRecording) {
          setTimeout(() => setAgentState("listening", "🎤 Listening"), 300);
        }
        break;

      case "error":
        console.error("[Server Error]", data.source, data.message);
        partialTranscriptText.textContent = data.message || "An error occurred";
        livePartialBar.classList.add("active");
        setAgentState("error", `❌ Error: ${data.source || "unknown"}`);
        // Show in diagnostics
        if (data.source === "llm" && diagLlmStatus) {
          diagLlmStatus.textContent = `❌ LLM error: ${data.message}`;
          diagLlmStatus.className = "diag-error";
        }
        break;

      case "vad_state":
        // VAD events don't need UI updates unless we want to show them
        break;

      case "pong":
        // Heartbeat acknowledged
        break;
    }
  }

  // ── Browser TTS Fallback ──────────────────────────────────────────────────────
  function enqueueBrowserTTS(text, turnId) {
    if (turnId !== activeTurnId) return;
    fallbackQueue.push({ text, turnId });
    if (!fallbackSpeaking) speakNextBrowserTTS();
  }

  function speakNextBrowserTTS() {
    const next = fallbackQueue.shift();
    if (!next || next.turnId !== activeTurnId) return;
    const generation = fallbackGeneration;
    fallbackSpeaking = true;
    const utterance = new SpeechSynthesisUtterance(next.text);
    const selectedIdx = ttsVoiceSelect.value;
    if (selectedIdx !== "" && speechSynthVoices[selectedIdx]) {
      utterance.voice = speechSynthVoices[selectedIdx];
    }
    utterance.rate = 1.05;
    utterance.onstart = () => {
      setAgentState("speaking", "🔊 Speaking (Browser TTS)");
      currentVolume = 0.5;
    };
    utterance.onend = () => {
      if (generation !== fallbackGeneration) return;
      fallbackSpeaking = false;
      currentVolume = 0;
      if (isRecording) {
        setAgentState("listening", "🎤 Listening");
      } else {
        setAgentState("ready", "Ready to Listen");
      }
      speakNextBrowserTTS();
    };
    window.speechSynthesis.speak(utterance);
  }

  function resetBrowserTTS() {
    fallbackGeneration += 1;
    fallbackQueue = [];
    fallbackSpeaking = false;
    window.speechSynthesis?.cancel();
  }

  // ── UI Helpers ────────────────────────────────────────────────────────────────
  function flashBargeinIndicator() {
    bargeinBadge.style.backgroundColor = "rgba(255, 51, 102, 0.3)";
    bargeinBadge.style.borderColor = "var(--danger)";
    setTimeout(() => {
      bargeinBadge.style.backgroundColor = "";
      bargeinBadge.style.borderColor = "";
    }, 1200);
  }

  function setAgentState(stateClass, label) {
    agentStateLabel.className = `state-indicator ${stateClass}`;
    stateText.textContent = label;
  }

  function setWsStatus(statusClass, label) {
    wsStatus.className = `status-badge ${statusClass}`;
    wsStatus.querySelector(".status-label").textContent = label;
  }

  // ── Microphone Recording ───────────────────────────────────────────────────────
  async function startRecording() {
    if (isRecording) return;
    try {
      await audioRecorder.start();
      isRecording = true;
      btnMic.classList.add("active");
      setAgentState("listening", "🎤 Listening");
    } catch (err) {
      console.error("[MIC] Failed to start:", err);
      alert("Could not access microphone. Please check browser permissions.");
    }
  }

  function stopRecording() {
    if (!isRecording) return;
    audioRecorder.stop();
    isRecording = false;
    btnMic.classList.remove("active");
    setAgentState("ready", "Ready to Listen");
  }

  async function toggleMicrophone() {
    if (!isRecording) {
      await startRecording();
    } else {
      stopRecording();
    }
  }

  btnMic.addEventListener("click", toggleMicrophone);

  // ── Push-to-Talk Spacebar ─────────────────────────────────────────────────────
  // FIX: `!e.repeat` prevents repeated keydown events when holding Space
  window.addEventListener("keydown", async (e) => {
    if (
      e.code === "Space" &&
      e.target.tagName !== "INPUT" &&
      e.target.tagName !== "TEXTAREA" &&
      !e.repeat
    ) {
      e.preventDefault();
      if (!isRecording) {
        isSpacePressed = true;
        await startRecording();
      }
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" && isSpacePressed) {
      e.preventDefault();
      isSpacePressed = false;
      stopRecording();
    }
  });

  // Clean up on page blur/hide
  window.addEventListener("blur", () => {
    if (isSpacePressed) {
      isSpacePressed = false;
      stopRecording();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && isSpacePressed) {
      isSpacePressed = false;
      stopRecording();
    }
  });

  // ── Chat Message Rendering ────────────────────────────────────────────────────
  function appendUserMessage(text) {
    const clean = text.trim();
    if (!clean) return;
    const now = Date.now();
    if (clean.toLowerCase() === lastAppendedUserText.toLowerCase() && now - lastAppendedTime < 2000) {
      return; // Skip duplicate within debounce window
    }
    lastAppendedUserText = clean;
    lastAppendedTime = now;
    const msgDiv = document.createElement("div");
    msgDiv.className = "message user-message";
    msgDiv.innerHTML = `
      <div class="avatar">YOU</div>
      <div class="bubble">
        <div class="meta">You</div>
        <div class="text">${escapeHtml(clean)}</div>
      </div>
    `;
    chatStream.appendChild(msgDiv);
    chatStream.scrollTop = chatStream.scrollHeight;
  }

  function appendAssistantMessagePlaceholder(turnId) {
    const msgDiv = document.createElement("div");
    msgDiv.className = "message assistant-message";
    msgDiv.id = `turn-${turnId}`;
    msgDiv.innerHTML = `
      <div class="avatar">AI</div>
      <div class="bubble">
        <div class="meta">Assistant • ${personaSelect.options[personaSelect.selectedIndex].text}</div>
        <div class="text message-text"></div>
      </div>
    `;
    chatStream.appendChild(msgDiv);
    chatStream.scrollTop = chatStream.scrollHeight;
    return msgDiv.querySelector(".message-text");
  }

  function escapeHtml(str) {
    return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  // ── Quick Prompt Chips ────────────────────────────────────────────────────────
  document.querySelectorAll(".prompt-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const text = chip.dataset.text;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "user_transcript", text: text, source: "prompt_chip" }));
      }
    });
  });

  // ── Clear Chat ────────────────────────────────────────────────────────────────
  btnClearChat.addEventListener("click", () => {
    chatStream.innerHTML = "";
    lastAppendedUserText = "";
    activeTurnId = null;
    if (diagTurnId) diagTurnId.textContent = "—";
    if (diagLastTranscript) diagLastTranscript.textContent = "—";
    audioPlayer.stopAndClear();
    resetBrowserTTS();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "clear_chat" }));
    }
  });

  // ── Settings Sync ─────────────────────────────────────────────────────────────
  personaSelect.addEventListener("change", () => {
    localStorage.setItem("apex_persona", personaSelect.value);
    syncSettingsWithBackend({ includeLlmProvider: false });
  });

  modelSelect.addEventListener("change", () => {
    // User explicitly changed LLM — now we track this and DO send it to backend
    userExplicitlyChangedLlm = true;
    if (modelSelect.value === "mock") {
      localStorage.removeItem("apex_model"); // Never persist mock to localStorage
    } else {
      localStorage.setItem("apex_model", modelSelect.value);
    }
    updateModelSelectLabel();
    syncSettingsWithBackend({ includeLlmProvider: true });
  });

  if (engineSelect) {
    engineSelect.addEventListener("change", () => {
      localStorage.setItem("apex_engine", engineSelect.value);
      syncSettingsWithBackend({ includeLlmProvider: false });
    });
  }

  /**
   * Sync session settings with backend over WebSocket.
   *
   * BUG FIX: includeLlmProvider defaults to false.
   * On initial WS connect we do NOT send llm_provider — the server
   * uses DEFAULT_LLM_PROVIDER from .env. Only explicit user changes
   * send llm_provider.
   */
  function syncSettingsWithBackend({ includeLlmProvider = false } = {}) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const settings = {
      agent_preset: personaSelect.value,
      voice_engine: engineSelect ? engineSelect.value : "assemblyai",
    };
    if (includeLlmProvider) {
      settings.llm_provider = modelSelect.value;
    }
    console.log("[Settings] Syncing with backend:", settings);
    ws.send(JSON.stringify({ type: "update_settings", settings }));
  }

  // ── Settings Modal ────────────────────────────────────────────────────────────
  btnOpenSettings.addEventListener("click", () => settingsModal.classList.add("open"));
  btnCloseSettings.addEventListener("click", () => settingsModal.classList.remove("open"));
  settingsModal.addEventListener("click", (e) => {
    if (e.target === settingsModal) settingsModal.classList.remove("open");
  });
  btnSaveSettings.addEventListener("click", () => {
    syncSettingsWithBackend({ includeLlmProvider: userExplicitlyChangedLlm });
    settingsModal.classList.remove("open");
  });

  // ── Canvas Waveform Visualizer ────────────────────────────────────────────────
  let phase = 0;
  function renderVisualizer() {
    requestAnimationFrame(renderVisualizer);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const baseAmplitude = 12;
    const dynamicAmp = baseAmplitude + currentVolume * 70;

    const orbScale = 1 + currentVolume * 0.8;
    orbCenter.style.transform = `scale(${orbScale})`;
    orbCenter.style.opacity = (0.5 + currentVolume * 0.5).toString();

    const colors = [
      "rgba(0, 229, 255, 0.7)",
      "rgba(138, 43, 226, 0.5)",
      "rgba(255, 0, 122, 0.4)",
    ];

    colors.forEach((color, i) => {
      ctx.beginPath();
      ctx.lineWidth = i === 0 ? 3 : 1.5;
      ctx.strokeStyle = color;
      const freq = 0.015 + i * 0.005;
      const speed = phase * (i % 2 === 0 ? 1 : -1) + i;
      for (let x = 0; x < width; x++) {
        const envelope = Math.sin((x / width) * Math.PI);
        const y = centerY + Math.sin(x * freq + speed) * dynamicAmp * envelope;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    });
    phase += 0.04;
  }
  renderVisualizer();

  // ── Start WebSocket ───────────────────────────────────────────────────────────
  connectWebSocket();
});
