import { useRef, useEffect } from 'react';
import MessageBubble, { TypingIndicator } from './MessageBubble';
import type { Message } from './MessageBubble';
import ChatInput from './ChatInput';
import './ChatArea.css';

interface ChatAreaProps {
  chatTitle: string;
  messages: Message[];
  isTyping: boolean;
  isGeneratingPdf?: boolean;
  onSendMessage: (message: string) => void;
  onUpdateTitle: (title: string) => void;
  onGenerateMemo?: () => void;
  onLinkClick?: (url: string) => void;
}

export default function ChatArea({
  chatTitle,
  messages,
  isTyping,
  isGeneratingPdf = false,
  onSendMessage,
  onUpdateTitle,
  onGenerateMemo,
  onLinkClick,
}: ChatAreaProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  return (
    <main className="chat-area">
      {/* ── Chat Header ────────────────────────────────── */}
      <header className="chat-header">
        <div className="chat-header-title-container">
          <input
            type="text"
            className="chat-header-title"
            value={chatTitle}
            onChange={(e) => onUpdateTitle(e.target.value)}
            id="chat-title-input"
          />
          {/* Outlined clean pencil SVG with no circular border */}
          <button className="chat-header-edit-btn" title="Rename chat" id="btn-rename-chat">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>
        </div>
        <div className="chat-header-actions" style={{ display: 'flex', gap: '8px' }}>
          {onGenerateMemo && messages.length > 0 && (
            <button 
              className="share-btn" 
              onClick={onGenerateMemo}
              disabled={isGeneratingPdf}
              style={{ padding: '6px 12px', opacity: isGeneratingPdf ? 0.7 : 1 }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '6px' }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
                <line x1="16" y1="13" x2="8" y2="13"></line>
                <line x1="16" y1="17" x2="8" y2="17"></line>
                <polyline points="10 9 9 9 8 9"></polyline>
              </svg>
              {isGeneratingPdf ? 'Generating...' : 'Generate Formal Memo'}
            </button>
          )}
          <button className="share-btn" id="btn-share">
            <svg className="share-btn-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
              <polyline points="16 6 12 2 8 6" />
              <line x1="12" y1="2" x2="12" y2="15" />
            </svg>
            Share
          </button>
        </div>
      </header>

      {/* ── Messages Area ──────────────────────────────── */}
      <div className="chat-messages-container">
        {messages.length === 0 ? (
          <div className="chat-empty-state">
            <div className="empty-state-logo">⚖</div>
            <h2 className="empty-state-title">LegalMind AI</h2>
            <p className="empty-state-subtitle">
              Your AI Legal Assistant for Pakistani Law. Ask questions about the Pakistan Penal Code,
              Constitution, Civil/Criminal procedures, or legal precedents.
            </p>
          </div>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} message={msg} onLinkClick={onLinkClick} />)
        )}
        {isTyping && <TypingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Chat Input ────────────────────────────────── */}
      <ChatInput onSend={onSendMessage} disabled={isTyping} />
    </main>
  );
}
