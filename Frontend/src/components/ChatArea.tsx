import { useRef, useEffect, useState } from 'react';
import MessageBubble, { TypingIndicator } from './MessageBubble';
import type { Message } from './MessageBubble';
import ChatInput from './ChatInput';
import lawLogo from '../assets/law-logo.png';
import pillarBg from '../assets/pillar.png';
import './ChatArea.css';

interface ChatAreaProps {
  chatTitle: string;
  messages: Message[];
  isTyping: boolean;
  isGeneratingPdf?: boolean;
  onSendMessage: (message: string, isVoiceMode?: boolean) => void;
  onUpdateTitle: (title: string) => void;
  onGenerateMemo?: () => void;
  onLinkClick?: (url: string) => void;
}

export default function ChatArea({
  chatTitle, messages, isTyping, isGeneratingPdf = false,
  onSendMessage, onUpdateTitle, onGenerateMemo, onLinkClick,
}: ChatAreaProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [shareCopied, setShareCopied] = useState(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleShare = async () => {
    const text = messages
      .map(m => `${m.role === 'user' ? 'You' : 'LegalMind'}:\n${m.content}`)
      .join('\n\n');
    try {
      await navigator.clipboard.writeText(text);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2500);
    } catch {
      alert('Could not copy to clipboard.');
    }
  };

  return (
    <main className="chat-area">
      {/* ── Header ─────────────────────────────────────── */}
      <header className="chat-header">
        <div className="chat-header-title-container">
          <input
            type="text"
            className="chat-header-title"
            value={chatTitle}
            onChange={(e) => onUpdateTitle(e.target.value)}
            id="chat-title-input"
          />
          <button className="chat-header-edit-btn" title="Rename chat" id="btn-rename-chat">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>
        </div>

        <div className="chat-header-actions">
          {onGenerateMemo && messages.length > 0 && (
            <button className="share-btn" onClick={onGenerateMemo} disabled={isGeneratingPdf}
              style={{ padding: '6px 12px', opacity: isGeneratingPdf ? 0.7 : 1 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '6px' }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              {isGeneratingPdf ? 'Generating...' : 'Generate Formal Memo'}
            </button>
          )}
          {messages.length > 0 && (
            <button className={`share-btn ${shareCopied ? 'share-copied' : ''}`}
              id="btn-share" onClick={handleShare} title="Copy chat to clipboard">
              {shareCopied ? (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Copied!
                </>
              ) : (
                <>
                  <svg className="share-btn-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
                    <polyline points="16 6 12 2 8 6" />
                    <line x1="12" y1="2" x2="12" y2="15" />
                  </svg>
                  Share
                </>
              )}
            </button>
          )}
        </div>
      </header>

      {/* ── Messages ───────────────────────────────────── */}
      <div className="chat-messages-container">
        {messages.length === 0 ? (
          <div className="chat-empty-state">
            {/* Background pillar image with fade */}
            <div className="empty-state-bg">
              <img src={pillarBg} alt="" className="empty-state-bg-img" />
            </div>

            <div className="empty-state-content">
              <div className="empty-state-logo-badge">
                <img className="empty-state-logo" src={lawLogo} alt="LegalMind Logo" />
              </div>
              <h2 className="empty-state-title">LegalMind AI</h2>
              <div className="empty-state-divider"></div>
              <p className="empty-state-subtitle">
                Your AI Legal Assistant for Pakistani Law.
              </p>
              <p className="empty-state-description">
                Ask questions about the Pakistan Penal Code, Constitution,
                Civil/Criminal procedures, or legal precedents.
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} message={msg} onLinkClick={onLinkClick} />)
        )}
        {isTyping && <TypingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Input ──────────────────────────────────────── */}
      <ChatInput onSend={onSendMessage} disabled={isTyping} />
    </main>
  );
}
