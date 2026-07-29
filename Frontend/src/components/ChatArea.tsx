import { useRef, useEffect } from 'react';
import MessageBubble, { TypingIndicator } from './MessageBubble';
import type { Message } from './MessageBubble';
import ChatInput from './ChatInput';
import './ChatArea.css';

interface ChatAreaProps {
  chatTitle: string;
  messages: Message[];
  isTyping: boolean;
  onSendMessage: (message: string) => void;
  onUpdateTitle: (title: string) => void;
}

export default function ChatArea({
  chatTitle,
  messages,
  isTyping,
  onSendMessage,
  onUpdateTitle,
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
        <div className="chat-header-actions">
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
          messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
        )}
        {isTyping && <TypingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Chat Input ────────────────────────────────── */}
      <ChatInput onSend={onSendMessage} disabled={isTyping} />
    </main>
  );
}
