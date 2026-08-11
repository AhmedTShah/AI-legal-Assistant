import { useState, useRef, useEffect } from 'react';
import './ChatInput.css';

type Mode = 'research' | 'web' | 'statutes';

interface ChatInputProps {
  onSend: (message: string, isVoiceMode?: boolean) => void;
  disabled?: boolean;
  backendUrl?: string;
}

const MODE_PREFIXES: Record<Mode, string> = {
  research: '',
  web:      'Web search: ',
  statutes: 'Statutes only: ',
};

export default function ChatInput({ onSend, disabled = false, backendUrl = 'http://localhost:8000' }: ChatInputProps) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState<Mode>('research');
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
    }
  }, [text]);

  const handleSend = (overrideText?: string, isVoiceMode = false) => {
    const messageToSend = overrideText !== undefined ? overrideText : text;
    const trimmed = messageToSend.trim();
    if (!trimmed || disabled) return;
    const prefix = MODE_PREFIXES[mode];
    onSend(prefix + trimmed, isVoiceMode);
    if (overrideText === undefined) setText('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const audioContextRef = useRef<AudioContext | null>(null);
  const vadAnimRef = useRef<number | null>(null);

  const toggleRecording = async () => {
    if (isRecording) {
      // Manual stop
      if (vadAnimRef.current) cancelAnimationFrame(vadAnimRef.current);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      setIsRecording(false);
    } else {
      // Start recording with VAD (Voice Activity Silence Detection)
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunksRef.current = [];
        const mediaRecorder = new MediaRecorder(stream);
        mediaRecorderRef.current = mediaRecorder;

        // Setup Web Audio API Analyser for silence detection
        const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
        audioContextRef.current = audioContext;
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        const microphone = audioContext.createMediaStreamSource(stream);
        microphone.connect(analyser);

        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        let speechDetected = false;
        let silenceStart = 0;
        const SILENCE_THRESHOLD = 12; // Volume threshold
        const SILENCE_DURATION_MS = 1200; // Auto-stop after 1.2s silence after speech

        const checkSilence = () => {
          if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') return;
          analyser.getByteFrequencyData(dataArray);

          let sum = 0;
          for (let i = 0; i < bufferLength; i++) {
            sum += dataArray[i];
          }
          const averageVolume = sum / bufferLength;

          if (averageVolume > SILENCE_THRESHOLD) {
            speechDetected = true;
            silenceStart = 0;
          } else if (speechDetected) {
            if (silenceStart === 0) {
              silenceStart = Date.now();
            } else if (Date.now() - silenceStart > SILENCE_DURATION_MS) {
              // Silence threshold reached -> Auto-Stop!
              if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
                mediaRecorderRef.current.stop();
                setIsRecording(false);
              }
              return;
            }
          }

          vadAnimRef.current = requestAnimationFrame(checkSilence);
        };

        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            audioChunksRef.current.push(event.data);
          }
        };

        mediaRecorder.onstop = async () => {
          if (vadAnimRef.current) cancelAnimationFrame(vadAnimRef.current);
          if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
            audioContextRef.current.close().catch(() => {});
          }
          stream.getTracks().forEach(track => track.stop());

          const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
          if (audioBlob.size < 500) return;

          setIsTranscribing(true);
          try {
            const formData = new FormData();
            formData.append('file', audioBlob, 'mic_recording.webm');

            const res = await fetch(`${backendUrl}/api/voice/transcribe`, {
              method: 'POST',
              body: formData,
            });

            if (!res.ok) throw new Error('Transcription failed.');
            const data = await res.json();

            if (data.text && data.text.trim()) {
              const transcribedText = data.text.trim();
              setText(transcribedText);
              // Automatically send to FastAPI chat pipeline with isVoiceMode=true!
              handleSend(transcribedText, true);
            }
          } catch (err: any) {
            alert(`Voice error: ${err.message}`);
          } finally {
            setIsTranscribing(false);
          }
        };

        mediaRecorder.start();
        setIsRecording(true);
        vadAnimRef.current = requestAnimationFrame(checkSilence);
      } catch (err) {
        alert('Microphone access denied or not supported in browser.');
      }
    }
  };

  return (
    <div className="chat-input-wrapper">
      <div className="chat-input-container">
        <textarea
          ref={textareaRef}
          className="chat-input-field"
          placeholder={isTranscribing ? "Transcribing audio (Whisper)..." : isRecording ? "Listening to your voice..." : "Ask me anything....."}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={disabled || isRecording || isTranscribing}
          id="chat-input"
        />

        <div className="chat-input-bottom-bar">
          <div className="chat-input-chips-inline">
            <button
              className={`chip ${mode === 'research' ? 'chip-active' : ''}`}
              id="chip-research"
              onClick={() => setMode('research')}
              title="Full AI research pipeline (default)"
            >
              <svg className="chip-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A5 5 0 0 0 8 8c0 1 .3 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>
                <line x1="9" y1="18" x2="15" y2="18"/>
                <line x1="10" y1="22" x2="14" y2="22"/>
              </svg>
              Research
            </button>

            <button
              className={`chip ${mode === 'web' ? 'chip-active' : ''}`}
              id="chip-web-search"
              onClick={() => setMode('web')}
              title="Search the web for legal resources"
            >
              <svg className="chip-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <line x1="2" y1="12" x2="22" y2="12"/>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10z"/>
              </svg>
              Web search
            </button>

            <button
              className={`chip ${mode === 'statutes' ? 'chip-active' : ''}`}
              id="chip-statutes"
              onClick={() => setMode('statutes')}
              title="Search Pakistan statutes only"
            >
              <svg className="chip-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
                <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
              </svg>
              Statutes
            </button>
          </div>

          <div className="chat-input-actions">
            <button
              className={`chat-input-voice-agent-btn ${isRecording ? 'recording' : ''}`}
              onClick={toggleRecording}
              disabled={disabled || isTranscribing}
              id="btn-voice-agent"
              title={isRecording ? "Listening... (Pause speaking to auto-send)" : "Voice Agent (Click to speak)"}
              aria-label="Voice Agent"
            >
              <svg className="soundwave-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <rect x="3" y="10" width="2.5" height="4" rx="1.25" />
                <rect x="7.5" y="6" width="2.5" height="12" rx="1.25" />
                <rect x="12" y="4" width="2.5" height="16" rx="1.25" />
                <rect x="16.5" y="7" width="2.5" height="10" rx="1.25" />
                <rect x="21" y="10" width="2.5" height="4" rx="1.25" />
              </svg>
            </button>

            <button
              className="chat-input-send-circle"
              onClick={() => handleSend()}
              disabled={!text.trim() || disabled || isRecording || isTranscribing}
              id="btn-send"
              aria-label="Send message"
              title="Send message"
            >
              <svg className="send-plane-svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
