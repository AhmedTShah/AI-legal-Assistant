import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import SettingsPanel from './components/SettingsPanel';
import type { UserSettings } from './components/SettingsPanel';
import type { Message } from './components/MessageBubble';
import './App.css';

interface Chat {
  id: string;
  title: string;
  messages: Message[];
  retrievedChunks?: any[];
}

const DEFAULT_SETTINGS: UserSettings = {
  displayName: 'Maya Johnes',
  userId:      'lawyer_abc',
  backendUrl:  'http://localhost:8000',
};

function loadSettings(): UserSettings {
  return {
    displayName: localStorage.getItem('legalmind_display_name') || DEFAULT_SETTINGS.displayName,
    userId:      localStorage.getItem('legalmind_user_id')      || DEFAULT_SETTINGS.userId,
    backendUrl:  localStorage.getItem('legalmind_backend_url')  || DEFAULT_SETTINGS.backendUrl,
  };
}

export default function App() {
  const [chats, setChats] = useState<Chat[]>(() => {
    try {
      const s = localStorage.getItem('legalmind_chats');
      if (s) {
        const p = JSON.parse(s);
        if (Array.isArray(p) && p.length > 0) return p;
      }
    } catch {}
    return [{ id: 'default', title: 'New Legal Consultation', messages: [] }];
  });

  const [activeChatId, setActiveChatId] = useState<string | null>(() =>
    localStorage.getItem('legalmind_active_chat_id') || 'default'
  );

  const [isTyping,          setIsTyping]          = useState(false);
  const [previewPdfUrl,     setPreviewPdfUrl]      = useState<string | null>(null);
  const [isGeneratingPdf,   setIsGeneratingPdf]    = useState(false);
  const [isSidebarCollapsed,setIsSidebarCollapsed] = useState(false);
  const [settingsOpen,      setSettingsOpen]       = useState(false);
  const [userSettings,      setUserSettings]       = useState<UserSettings>(loadSettings);

  const activeChat = chats.find(c => c.id === activeChatId) || null;
  const API = userSettings.backendUrl;

  // Persist chats
  useEffect(() => { localStorage.setItem('legalmind_chats', JSON.stringify(chats)); }, [chats]);

  // Persist active chat id
  useEffect(() => {
    if (activeChatId) localStorage.setItem('legalmind_active_chat_id', activeChatId);
    else              localStorage.removeItem('legalmind_active_chat_id');
  }, [activeChatId]);

  // Sync history on selection
  useEffect(() => {
    if (activeChatId) syncChatHistory(activeChatId);
  }, [activeChatId]);

  const syncChatHistory = async (id: string) => {
    try {
      const res = await fetch(`${API}/api/chat/${id}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.messages?.length) {
        setChats(prev => prev.map(c => c.id !== id ? c : {
          ...c,
          messages: data.messages.map((m: any, i: number) => ({
            id: `${id}-${i}`,
            role: m.role === 'human' ? 'user' : 'ai',
            content: m.content,
            timestamp: new Date(),
          })),
        }));
      }
    } catch {}
  };

  const handleNewChat = () => {
    const newId = Date.now().toString();
    setChats(prev => [{ id: newId, title: 'New Legal Consultation', messages: [] }, ...prev]);
    setActiveChatId(newId);
    setPreviewPdfUrl(null);
  };

  const handleSelectChat = (id: string) => { setActiveChatId(id); setPreviewPdfUrl(null); };

  const handleDeleteChat = async (id: string) => {
    setChats(prev => {
      const updated = prev.filter(c => c.id !== id);
      if (activeChatId === id) {
        if (updated.length > 0) {
          setActiveChatId(updated[0].id);
        } else {
          const newId = Date.now().toString();
          setActiveChatId(newId);
          return [{ id: newId, title: 'New Legal Consultation', messages: [] }];
        }
      }
      return updated;
    });
    try { await fetch(`${API}/api/chat/${id}`, { method: 'DELETE' }); } catch {}
  };

  const handleUpdateTitle = (newTitle: string) => {
    setChats(prev => prev.map(c => c.id === activeChatId ? { ...c, title: newTitle } : c));
  };

  const handleSendMessage = (content: string) => {
    if (!activeChatId) return;
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content, timestamp: new Date() };
    setChats(prev => prev.map(c => {
      if (c.id !== activeChatId) return c;
      const msgs = [...c.messages, userMsg];
      const title = c.messages.length === 0
        ? (content.length > 30 ? content.slice(0, 30) + '...' : content)
        : c.title;
      return { ...c, title, messages: msgs };
    }));

    setIsTyping(true);
    fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: content, session_id: activeChatId, user_id: userSettings.userId }),
    })
      .then(res => { if (!res.ok) throw new Error('Failed to reach the legal assistant server.'); return res.json(); })
      .then(data => {
        const aiMsg: Message = { id: Date.now().toString(), role: 'ai', content: data.response, timestamp: new Date() };
        setChats(prev => prev.map(c => {
          if (c.id !== activeChatId) return c;
          return { ...c, messages: [...c.messages, aiMsg], retrievedChunks: [...(c.retrievedChunks || []), ...(data.retrieved_chunks || [])] };
        }));
      })
      .catch(err => {
        const errMsg: Message = { id: Date.now().toString(), role: 'ai', content: `Error: ${err.message}`, timestamp: new Date() };
        setChats(prev => prev.map(c => c.id !== activeChatId ? c : { ...c, messages: [...c.messages, errMsg] }));
      })
      .finally(() => setIsTyping(false));
  };

  const handleGenerateMemo = async () => {
    if (!activeChat || activeChat.messages.length === 0) return;
    setIsGeneratingPdf(true);
    try {
      const historyStr = activeChat.messages.map(m => `${m.role.toUpperCase()}:\n${m.content}`).join('\n\n');
      const res = await fetch(`${API}/api/generate_pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: historyStr, retrieved_chunks: activeChat.retrievedChunks || [] }),
      });
      if (!res.ok) throw new Error('Failed to generate PDF memo.');
      const blob = await res.blob();
      setPreviewPdfUrl(URL.createObjectURL(blob));
    } catch (err: any) {
      alert(err.message || 'Error generating PDF memo.');
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  // ── Settings handlers ──────────────────────────────────────────────────────
  const handleSaveSettings = (s: UserSettings) => {
    localStorage.setItem('legalmind_display_name', s.displayName);
    localStorage.setItem('legalmind_user_id',      s.userId);
    localStorage.setItem('legalmind_backend_url',  s.backendUrl);
    setUserSettings(s);
  };

  const handleClearCurrentSession = async () => {
    if (!activeChatId) return;
    try { await fetch(`${API}/api/chat/${activeChatId}`, { method: 'DELETE' }); } catch {}
    setChats(prev => prev.map(c => c.id === activeChatId ? { ...c, messages: [], retrievedChunks: [] } : c));
  };

  const handleClearAllHistory = async () => {
    for (const c of chats) {
      try { await fetch(`${API}/api/chat/${c.id}`, { method: 'DELETE' }); } catch {}
    }
    const newId = Date.now().toString();
    setChats([{ id: newId, title: 'New Legal Consultation', messages: [] }]);
    setActiveChatId(newId);
    setPreviewPdfUrl(null);
    setSettingsOpen(false);
  };

  return (
    <div className={`app-container ${isSidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        isCollapsed={isSidebarCollapsed}
        displayName={userSettings.displayName}
        onNewChat={handleNewChat}
        onSelectChat={handleSelectChat}
        onDeleteChat={handleDeleteChat}
        onToggleSidebar={() => setIsSidebarCollapsed(p => !p)}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="main-content-wrapper">
        {activeChat ? (
          <ChatArea
            chatTitle={activeChat.title}
            messages={activeChat.messages}
            isTyping={isTyping}
            isGeneratingPdf={isGeneratingPdf}
            onSendMessage={handleSendMessage}
            onUpdateTitle={handleUpdateTitle}
            onGenerateMemo={handleGenerateMemo}
            onLinkClick={url => setPreviewPdfUrl(url)}
          />
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280' }}>
            Select a chat to begin research.
          </div>
        )}

        {previewPdfUrl && (
          <div className="preview-pane">
            <div className="preview-pane-header">
              <span>Formal Legal Memo Preview</span>
              <button className="preview-pane-close" onClick={() => setPreviewPdfUrl(null)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
              </button>
            </div>
            <iframe className="preview-iframe" src={previewPdfUrl} title="Legal Memo PDF" />
          </div>
        )}
      </div>

      <SettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={userSettings}
        onSave={handleSaveSettings}
        onClearCurrentSession={handleClearCurrentSession}
        onClearAllHistory={handleClearAllHistory}
      />
    </div>
  );
}
