import { useState, useRef, useEffect } from 'react';
import './ChatInput.css';

type Mode = 'research' | 'web' | 'statutes';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

const MODE_PREFIXES: Record<Mode, string> = {
  research: '',
  web:      'Web search: ',
  statutes: 'Statutes only: ',
};

export default function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState<Mode>('research');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
    }
  }, [text]);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    const prefix = MODE_PREFIXES[mode];
    onSend(prefix + trimmed);
    setText('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <div className="chat-input-wrapper">
      <div className="chat-input-container">
        <textarea
          ref={textareaRef}
          className="chat-input-field"
          placeholder="Ask me anything....."
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={disabled}
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

          <button
            className="chat-input-send-circle"
            onClick={handleSend}
            disabled={!text.trim() || disabled}
            id="btn-send"
            aria-label="Send message"
          >
            <svg className="waveform-svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="6" y1="10" x2="6" y2="14"/>
              <line x1="10" y1="6" x2="10" y2="18"/>
              <line x1="14" y1="8" x2="14" y2="16"/>
              <line x1="18" y1="11" x2="18" y2="13"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
