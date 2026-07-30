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

const parseMarkdown = (text: string) => {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let inList = false;
  let listItems: React.ReactNode[] = [];

  const parseInline = (inlineText: string): React.ReactNode[] => {
    // Split by markdown link [title](url) and bold **text**
    const combinedRegex = /(\[[^\]]+\]\(https?:\/\/[^\s\)]+\)|\*\*[^*]+\*\*)/g;
    const parts = inlineText.split(combinedRegex);

    return parts.map((part, index) => {
      if (part.startsWith('[') && part.includes('](') && part.endsWith(')')) {
        const titleMatch = part.match(/\[([^\]]+)\]/);
        const urlMatch = part.match(/\((https?:\/\/[^\s\)]+)\)/);
        if (titleMatch && urlMatch) {
          return (
            <a
              key={index}
              href={urlMatch[1]}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#3b82f6', textDecoration: 'underline', fontWeight: 500 }}
            >
              🔗 {titleMatch[1]}
            </a>
          );
        }
      }
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    
    // Check if it's a bullet point (starts with * or -)
    if (trimmed.startsWith('*') || trimmed.startsWith('-')) {
      const content = trimmed.substring(1).trim();
      inList = true;
      listItems.push(<li key={`li-${index}`}>{parseInline(content)}</li>);
    } else {
      // If we were in a list, close it first
      if (inList) {
        elements.push(
          <ul key={`ul-${index}`} className="message-list">
            {listItems}
          </ul>
        );
        listItems = [];
        inList = false;
      }
      
      if (trimmed === '') {
        elements.push(<div key={`space-${index}`} className="message-paragraph-space" />);
      } else {
        elements.push(<p key={`p-${index}`} className="message-paragraph">{parseInline(line)}</p>);
      }
    }
  });

  // Close any remaining list
  if (inList) {
    elements.push(
      <ul key="ul-final" className="message-list">
        {listItems}
      </ul>
    );
  }

  return elements;
};

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
        {parseMarkdown(message.content)}
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
