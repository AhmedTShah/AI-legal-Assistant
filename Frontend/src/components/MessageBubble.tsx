import { useState } from 'react';
import './MessageBubble.css';

export interface Message {
  id: string;
  role: 'user' | 'ai';
  content: string;
  timestamp: Date;
}

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API not available
    }
  };

  return (
    <div className={`message ${isUser ? 'message-user' : 'message-ai'}`}>
      <div className="message-content">
        {message.content}
      </div>

      {/* Action buttons only for AI messages */}
      {!isUser && (
        <div className="message-actions">
          <button className="message-action-btn" onClick={handleCopy} id={`copy-${message.id}`}>
            <span className="message-action-icon">{copied ? '✓' : '📋'}</span>
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button className="message-action-btn" id={`retry-${message.id}`}>
            <span className="message-action-icon">🔄</span>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

/* Typing indicator component */
export function TypingIndicator() {
  return (
    <div className="typing-indicator">
      <div className="typing-dot" />
      <div className="typing-dot" />
      <div className="typing-dot" />
    </div>
  );
}
