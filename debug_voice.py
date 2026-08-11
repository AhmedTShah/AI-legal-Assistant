import time
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("VoiceDebug")

print("=" * 60)
print("🔊 LAWMIND VOICE PIPELINE DIAGNOSTIC SCRIPT")
print("=" * 60)

# STEP 1: Test Hugging Face Hub Connectivity
print("\n[STEP 1] Testing Hugging Face Hub Connection...")
t0 = time.time()
try:
    import urllib.request
    req = urllib.request.urlopen("https://huggingface.co", timeout=5)
    print(f"✅ Hugging Face Hub accessible! (Took {time.time() - t0:.2f}s)")
except Exception as e:
    print(f"❌ Hugging Face Hub Connection Failed/Timed Out: {e}")

# STEP 2: Test faster-whisper Initialization
print("\n[STEP 2] Testing faster-whisper Model Loading...")
t0 = time.time()
try:
    from faster_whisper import WhisperModel
    print("Attempting to load faster-whisper 'tiny.en' on CPU...")
    # Load model with explicit timeout or local cache
    model = WhisperModel("tiny.en", device="cpu", compute_type="default")
    print(f"✅ faster-whisper initialized successfully in {time.time() - t0:.2f}s!")
except Exception as e:
    print(f"❌ faster-whisper failed: {e} (Took {time.time() - t0:.2f}s)")

# STEP 3: Test Gemini Audio Multimodal API
print("\n[STEP 3] Testing Gemini Multimodal Audio Transcription...")
t0 = time.time()
try:
    import google.generativeai as genai
    from config import GEMINI_API_KEY, CHAT_MODEL
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(CHAT_MODEL)
    print(f"✅ Gemini API configured with model '{CHAT_MODEL}' in {time.time() - t0:.2f}s!")
except Exception as e:
    print(f"❌ Gemini API test failed: {e}")

# STEP 4: Test Piper TTS CLI / Execution
print("\n[STEP 4] Testing Piper TTS Engine...")
t0 = time.time()
try:
    from services.voice_service import PiperTTS
    tts = PiperTTS()
    audio_b64 = tts.synthesize_to_base64("Testing Piper TTS audio synthesis.")
    if audio_b64:
        print(f"✅ Piper TTS synthesized audio in {time.time() - t0:.2f}s! (Data length: {len(audio_b64)} chars)")
    else:
        print("⚠️ Piper TTS returned empty output (check fallback/piper ONNX installation).")
except Exception as e:
    print(f"❌ Piper TTS test failed: {e}")

print("\n" + "=" * 60)
print("🏁 DIAGNOSTIC COMPLETE")
print("=" * 60)
