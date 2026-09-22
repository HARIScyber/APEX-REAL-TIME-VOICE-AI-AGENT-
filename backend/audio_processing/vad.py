import math
import struct


class VoiceActivityDetector:
    """Small PCM VAD that reports speech transitions for turn control."""

    def __init__(
        self,
        energy_threshold_db: float = -42.0,
        silence_timeout_ms: int = 650,
        speech_confirmation_ms: int = 120,
        sample_rate: int = 16000,
    ):
        self.energy_threshold_db = energy_threshold_db
        self.silence_timeout_ms = silence_timeout_ms
        self.speech_confirmation_ms = speech_confirmation_ms
        self.sample_rate = sample_rate
        self.is_speaking = False
        self.speech_duration_ms = 0.0
        self.silent_duration_ms = 0.0

    def process_chunk(self, pcm_data: bytes) -> dict:
        if len(pcm_data) < 2:
            return self._result(False, -99.0, False, False, False)

        sample_count = len(pcm_data) // 2
        duration_ms = sample_count * 1000.0 / self.sample_rate
        try:
            samples = struct.unpack(f"<{sample_count}h", pcm_data[: sample_count * 2])
            rms = math.sqrt(sum(sample * sample for sample in samples) / sample_count)
            energy_db = 20 * math.log10(rms / 32768.0) if rms else -100.0
        except (struct.error, ValueError, OverflowError):
            energy_db = -100.0

        is_speech = energy_db > self.energy_threshold_db
        speech_started = False
        speech_confirmed = False
        speech_ended = False

        if is_speech:
            self.silent_duration_ms = 0.0
            self.speech_duration_ms += duration_ms
            if not self.is_speaking:
                self.is_speaking = True
                speech_started = True
            speech_confirmed = self.speech_duration_ms >= self.speech_confirmation_ms
        elif self.is_speaking:
            self.silent_duration_ms += duration_ms
            if self.silent_duration_ms >= self.silence_timeout_ms:
                self.is_speaking = False
                self.speech_duration_ms = 0.0
                self.silent_duration_ms = 0.0
                speech_ended = True

        return self._result(is_speech, energy_db, speech_started, speech_confirmed, speech_ended)

    def _result(self, is_speech, energy_db, speech_started, speech_confirmed, speech_ended):
        return {
            "is_speech": is_speech,
            "energy_db": round(energy_db, 1),
            "speech_started": speech_started,
            "speech_confirmed": speech_confirmed,
            "speech_ended": speech_ended,
            "is_speaking_state": self.is_speaking,
        }

    def reset(self) -> None:
        self.is_speaking = False
        self.speech_duration_ms = 0.0
        self.silent_duration_ms = 0.0
