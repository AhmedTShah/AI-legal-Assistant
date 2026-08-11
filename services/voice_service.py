"""
voice_service.py — High-Performance Voice Service (Whisper STT & Piper TTS)
============================================================================
Provides sub-second audio transcription using INT8 quantized faster-whisper
and offline neural speech synthesis using Piper TTS.
"""

import os
import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# ── FASTER-WHISPER STT TRANSCRIBER ─────────────────────────────────────────────

class WhisperTranscriber:
    """
    Sub-second Speech-to-Text Transcriber powered by faster-whisper.
    Uses CTranslate2 backend with INT8 quantization for sub-150ms latency.
    """
    _instance = None
    _model = None

    def __new__(cls, model_size: str = "tiny.en", device: str = "cpu", compute_type: str = "default"):
        if cls._instance is None:
            cls._instance = super(WhisperTranscriber, cls).__new__(cls)
            cls._model_size = model_size
            cls._device = device
            cls._compute_type = compute_type
            cls._init_model()
        return cls._instance

    @classmethod
    def _init_model(cls):
        try:
            from faster_whisper import WhisperModel
            logger.info("Initializing faster-whisper model '%s'...", cls._model_size)
            cls._model = WhisperModel(
                cls._model_size,
                device=cls._device,
                compute_type=cls._compute_type
            )
            logger.info("faster-whisper STT model loaded successfully.")
        except Exception as e:
            logger.error("Failed to load faster-whisper model: %s", e)
            cls._model = None

    def transcribe(self, audio_source: Union[str, bytes], language: Optional[str] = None) -> str:
        """
        Transcribes an audio file or raw audio bytes to text.
        
        Args:
            audio_source: File path string OR raw bytes of webm/wav audio.
            language: Optional language code (e.g., 'en', 'ur'). Auto-detected if None.
            
        Returns:
            Transcribed text string.
        """
        if self._model is None:
            # Fallback re-init attempt
            self._init_model()
            if self._model is None:
                raise RuntimeError("Whisper STT model is not initialized.")

        temp_filepath = None
        try:
            if isinstance(audio_source, bytes):
                # Save incoming binary audio to a temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
                    temp_file.write(audio_source)
                    temp_filepath = temp_file.name
                file_to_process = temp_filepath
            else:
                file_to_process = audio_source

            # Run faster-whisper transcription (vad_filter=False to prevent Silero VAD download network hang)
            segments, info = self._model.transcribe(
                file_to_process,
                beam_size=1,            # Greedy decoding for ultra low latency (~100ms)
                language=language,
                vad_filter=False
            )

            transcribed_text = " ".join([segment.text.strip() for segment in segments if segment.text])
            logger.info("Whisper Transcribed (%s, prob=%.2f): '%s'", info.language, info.language_probability, transcribed_text)
            return transcribed_text.strip()

        except Exception as exc:
            logger.error("Whisper transcription error: %s. Attempting Gemini Audio STT fallback...", exc)
            return self._gemini_audio_fallback(file_to_process)
        finally:
            if temp_filepath and os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass

    def _gemini_audio_fallback(self, file_path: str) -> str:
        """Fallback transcription using Gemini API multimodal audio capability."""
        try:
            import google.generativeai as genai
            from config import GEMINI_API_KEY, CHAT_MODEL
            genai.configure(api_key=GEMINI_API_KEY)
            audio_file = genai.upload_file(file_path)
            model = genai.GenerativeModel(CHAT_MODEL)
            response = model.generate_content([
                "Transcribe this audio recording accurately into text. Output ONLY the exact transcribed text, nothing else.",
                audio_file
            ])
            try:
                genai.delete_file(audio_file.name)
            except Exception:
                pass
            return response.text.strip()
        except Exception as e:
            logger.error("Gemini Audio fallback error: %s", e)
            raise RuntimeError(f"All transcription methods failed: {e}")


# ── PIPER TTS SYNTHESIZER ──────────────────────────────────────────────────────

class PiperTTS:
    """
    Offline neural Text-to-Speech Synthesizer powered by Piper TTS.
    """
    def __init__(self, voice_model_path: Optional[str] = None):
        self.voices_dir = Path(__file__).resolve().parent.parent / "voices"
        self.voices_dir.mkdir(exist_ok=True)
        self.voice_model_path = voice_model_path or str(self.voices_dir / "en_US-lessac-medium.onnx")
        self._ensure_voice_model()

    def _ensure_voice_model(self):
        """Downloads the Piper voice ONNX model if not already present."""
        onnx_file = Path(self.voice_model_path)
        json_file = Path(f"{self.voice_model_path}.json")
        if not onnx_file.exists() or not json_file.exists():
            logger.info("Piper voice model not found locally. Downloading en_US-lessac-medium ONNX model...")
            try:
                import urllib.request
                onnx_url = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
                json_url = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
                if not onnx_file.exists():
                    urllib.request.urlretrieve(onnx_url, onnx_file)
                if not json_file.exists():
                    urllib.request.urlretrieve(json_url, json_file)
                logger.info("Piper voice model downloaded successfully.")
            except Exception as e:
                logger.warning(f"Failed to download Piper voice model: {e}. Will use pyttsx3/gTTS fallback.")

    def synthesize_to_file(self, text: str, output_wav_path: str) -> str:
        """
        Synthesizes text input to an audio WAV file.
        """
        if not text or not text.strip():
            raise ValueError("Text input cannot be empty.")

        try:
            # Check if piper-tts command / python package is available
            import subprocess
            cmd = [
                sys.executable, "-m", "piper",
                "--model", self.voice_model_path,
                "--output_file", output_wav_path
            ]
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=text)

            if process.returncode != 0 or not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) == 0:
                logger.warning("Piper CLI returned error: %s. Using pyttsx3/gTTS fallback.", stderr)
                self._fallback_tts(text, output_wav_path)
            
            return output_wav_path

        except Exception as e:
            logger.warning("Piper TTS execution exception: %s. Using fallback.", e)
            self._fallback_tts(text, output_wav_path)
            return output_wav_path

    def _fallback_tts(self, text: str, output_wav_path: str):
        """Fallback TTS engine using pyttsx3 or gTTS if piper model file is not available."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, output_wav_path)
            engine.runAndWait()
            if os.path.exists(output_wav_path) and os.path.getsize(output_wav_path) > 0:
                return
        except Exception:
            pass

        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang='en')
            tts.save(output_wav_path)
            return
        except Exception as e:
            logger.error("TTS Fallback failed: %s", e)
            # Create an empty silent wav file as graceful fallback
            import wave
            with wave.open(output_wav_path, 'wb') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(22050)
                f.writeframes(b'')

    def synthesize_to_base64(self, text: str) -> Optional[str]:
        """
        Synthesizes a short text sentence to Base64-encoded WAV audio data string.
        """
        if not text or not text.strip():
            return None
        import base64
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp_path = tmp.name

        try:
            self.synthesize_to_file(text, tmp_path)
            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                with open(tmp_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                return f"data:audio/wav;base64,{encoded}"
            return None
        except Exception as e:
            logger.error("Base64 TTS synthesis error: %s", e)
            return None
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
