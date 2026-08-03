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
  onLinkClick?: (url: string) => void;
}

const parseMarkdown = (text: string, onLinkClick?: (url: string) => void): React.ReactNode[] => {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let inBulletList = false;
  let bulletItems: React.ReactNode[] = [];
  let inOrderedList = false;
  let orderedItems: React.ReactNode[] = [];

  const closeLists = (key: string) => {
    if (inBulletList) {
      elements.push(<ul key={`ul-${key}`} className="message-list">{bulletItems}</ul>);
      bulletItems = []; inBulletList = false;
    }
    if (inOrderedList) {
      elements.push(<ol key={`ol-${key}`} className="message-ordered-list">{orderedItems}</ol>);
      orderedItems = []; inOrderedList = false;
    }
  };

  const parseInline = (inlineText: string): React.ReactNode[] => {
    const INLINE_RE = /(\*\*[^*\n]+\*\*|\*(?!\*)[^*\n]+\*(?!\*)|`[^`\n]+`|\[[^\]\n]+\]\([^)\n]+\)|\[[^\]\n]+\])/g;
    const parts = inlineText.split(INLINE_RE);
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      if (part.startsWith('*') && part.endsWith('*') && part.length > 2 && !part.startsWith('**'))
        return <em key={i}>{part.slice(1, -1)}</em>;
      if (part.startsWith('`') && part.endsWith('`') && part.length > 2)
        return <code key={i} className="message-inline-code">{part.slice(1, -1)}</code>;
      if (part.startsWith('[') && part.includes('](') && part.endsWith(')')) {
        const bc = part.indexOf('](');
        const title = part.slice(1, bc);
        const url = part.slice(bc + 2, -1);
        return <a key={i} href={url} target="_blank" rel="noopener noreferrer" className="citation-pill citation-link">🔗 {title}</a>;
      }
      if (part.startsWith('[') && part.endsWith(']') && !part.includes('](')) {
        return <span key={i} className="citation-pill citation-text">{part.slice(1, -1)}</span>;
      }
      return part;
    });
  };

  lines.forEach((line, idx) => {
    const key = String(idx);
    const trimmed = line.trim();
    if (trimmed.startsWith('### ')) { closeLists(key); elements.push(<h3 key={`h3-${key}`} className="message-h3">{parseInline(trimmed.slice(4))}</h3>); return; }
    if (trimmed.startsWith('## '))  { closeLists(key); elements.push(<h2 key={`h2-${key}`} className="message-h2">{parseInline(trimmed.slice(3))}</h2>); return; }
    if (trimmed.startsWith('# '))   { closeLists(key); elements.push(<h1 key={`h1-${key}`} className="message-h1">{parseInline(trimmed.slice(2))}</h1>); return; }
    if (trimmed === '---' || trimmed === '***' || trimmed === '___') { closeLists(key); elements.push(<hr key={`hr-${key}`} className="message-hr" />); return; }
    if (/^[-*] /.test(trimmed)) {
      if (inOrderedList) closeLists(key);
      inBulletList = true;
      bulletItems.push(<li key={`li-${key}`}>{parseInline(trimmed.slice(2).trim())}</li>);
      return;
    }
    if (/^\d+\. /.test(trimmed)) {
      if (inBulletList) closeLists(key);
      inOrderedList = true;
      orderedItems.push(<li key={`oli-${key}`}>{parseInline(trimmed.replace(/^\d+\. /, '').trim())}</li>);
      return;
    }
    if (trimmed === '') { closeLists(key); elements.push(<div key={`space-${key}`} className="message-paragraph-space" />); return; }
    closeLists(key);
    elements.push(<p key={`p-${key}`} className="message-paragraph">{parseInline(line)}</p>);
  });

  closeLists('final');
  return elements;
};

export default function MessageBubble({ message, onLinkClick }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const handleCopy = async () => {
    try { await navigator.clipboard.writeText(message.content); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch {}
  };
  return (
    <div className={`message ${isUser ? 'message-user' : 'message-ai'}`}>
      <div className="message-content">{parseMarkdown(message.content, onLinkClick)}</div>
      {!isUser && (
        <div className="message-actions">
          <button className="message-action-btn" onClick={handleCopy} id={`copy-${message.id}`}>
            <span className="message-action-icon" style={{ display: 'flex' }}>
              {copied ? (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              ) : (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              )}
            </span>
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button className="message-action-btn" id={`retry-${message.id}`}>
            <span className="message-action-icon" style={{ display: 'flex' }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            </span>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="typing-indicator">
      <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
    </div>
  );
}
