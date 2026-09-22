const AUDIO_WORKLET_CODE = `
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frameCount = 1600;
    this.buffer = new Float32Array(this.frameCount);
    this.index = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.buffer[this.index++] = channel[index];
      if (this.index === this.frameCount) {
        let squareSum = 0;
        const pcm = new Int16Array(this.frameCount);
        for (let sample = 0; sample < this.frameCount; sample += 1) {
          const value = Math.max(-1, Math.min(1, this.buffer[sample]));
          squareSum += value * value;
          pcm[sample] = value < 0 ? value * 0x8000 : value * 0x7fff;
        }
        this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(squareSum / this.frameCount) }, [pcm.buffer]);
        this.index = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm-recorder-worklet", PCMProcessor);
`;

class AudioStreamRecorder {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 16000;
    this.onAudioData = options.onAudioData || (() => {});
    this.onVolumeChange = options.onVolumeChange || (() => {});
    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.workletNode = null;
    this.silentGain = null;
    this.workletBlobUrl = null;
    this.isRecording = false;
  }

  async start() {
    if (this.isRecording) return;
    if (!window.AudioWorkletNode) throw new Error("AudioWorklet is required for microphone streaming.");
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: this.sampleRate });
    if (this.audioContext.state === "suspended") await this.audioContext.resume();
    if (!this.audioContext.audioWorklet) throw new Error("AudioWorklet is unavailable in this browser.");
    if (!this.workletBlobUrl) {
      this.workletBlobUrl = URL.createObjectURL(new Blob([AUDIO_WORKLET_CODE], { type: "application/javascript" }));
    }
    await this.audioContext.audioWorklet.addModule(this.workletBlobUrl);
    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.workletNode = new AudioWorkletNode(this.audioContext, "pcm-recorder-worklet");
    this.silentGain = this.audioContext.createGain();
    this.silentGain.gain.value = 0;
    this.workletNode.port.onmessage = ({ data }) => {
      if (!this.isRecording) return;
      this.onVolumeChange(data.rms || 0);
      if (data.pcm) this.onAudioData(data.pcm);
    };
    this.sourceNode.connect(this.workletNode);
    this.workletNode.connect(this.silentGain);
    this.silentGain.connect(this.audioContext.destination);
    this.isRecording = true;
  }

  stop() {
    if (!this.isRecording) return;
    this.isRecording = false;
    if (this.workletNode) this.workletNode.port.onmessage = null;
    [this.sourceNode, this.workletNode, this.silentGain].forEach((node) => {
      if (node) node.disconnect();
    });
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    this.audioContext?.close();
    this.sourceNode = null;
    this.workletNode = null;
    this.silentGain = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.onVolumeChange(0);
  }
}

class StreamingAudioPlayer {
  constructor(options = {}) {
    this.onVolumeChange = options.onVolumeChange || (() => {});
    this.onPlaybackStateChange = options.onPlaybackStateChange || (() => {});
    this.audioContext = null;
    this.analyserNode = null;
    this.activeTurnId = null;
    this.nextPlaybackTime = 0;
    this.sources = new Set();
    this.generation = 0;
    this.animationFrame = null;
  }

  _initContext() {
    if (!this.audioContext || this.audioContext.state === "closed") {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      this.analyserNode = this.audioContext.createAnalyser();
      this.analyserNode.fftSize = 256;
      this.analyserNode.connect(this.audioContext.destination);
    }
    if (this.audioContext.state === "suspended") this.audioContext.resume();
  }

  beginTurn(turnId) {
    if (turnId === this.activeTurnId) return;
    this.stopAndClear();
    this.activeTurnId = turnId;
  }

  enqueuePcmChunk(encodedAudio, turnId, sampleRate = 16000) {
    if (!encodedAudio || turnId !== this.activeTurnId) return;
    this._initContext();
    let bytes;
    try {
      const binary = atob(encodedAudio);
      bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    } catch (_) {
      return;
    }
    if (bytes.byteLength < 2 || bytes.byteLength % 2 !== 0) return;
    const sampleCount = bytes.byteLength / 2;
    const buffer = this.audioContext.createBuffer(1, sampleCount, sampleRate);
    const output = buffer.getChannelData(0);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let index = 0; index < sampleCount; index += 1) output[index] = view.getInt16(index * 2, true) / 32768;
    this._schedule(buffer);
  }

  _schedule(buffer) {
    const generation = this.generation;
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyserNode);
    const startAt = Math.max(this.nextPlaybackTime, this.audioContext.currentTime + 0.035);
    this.nextPlaybackTime = startAt + buffer.duration;
    this.sources.add(source);
    this.onPlaybackStateChange(true);
    source.onended = () => {
      this.sources.delete(source);
      if (generation === this.generation && this.sources.size === 0 && this.audioContext.currentTime >= this.nextPlaybackTime - 0.01) {
        this.onPlaybackStateChange(false);
        this.onVolumeChange(0);
      }
    };
    source.start(startAt);
    this._trackVisualizer();
  }

  _trackVisualizer() {
    if (!this.analyserNode || this.sources.size === 0) return;
    const values = new Uint8Array(this.analyserNode.frequencyBinCount);
    this.analyserNode.getByteFrequencyData(values);
    const average = values.reduce((total, value) => total + value, 0) / (values.length * 255);
    this.onVolumeChange(average);
    cancelAnimationFrame(this.animationFrame);
    this.animationFrame = requestAnimationFrame(() => this._trackVisualizer());
  }

  stopAndClear() {
    this.generation += 1;
    this.nextPlaybackTime = 0;
    this.sources.forEach((source) => {
      source.onended = null;
      try { source.stop(); } catch (_) {}
      source.disconnect();
    });
    this.sources.clear();
    cancelAnimationFrame(this.animationFrame);
    this.onPlaybackStateChange(false);
    this.onVolumeChange(0);
    window.speechSynthesis?.cancel();
  }
}
