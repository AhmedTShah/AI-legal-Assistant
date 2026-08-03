import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import type { Message } from './components/MessageBubble';
import './App.css';

interface Chat {
  id: string;
  title: string;
  messages: Message[];
  retrievedChunks?: any[];
}

export default function App() {
  const [chats, setChats] = useState<Chat[]>(() => {
    const savedChats = localStorage.getItem('legalmind_chats');
    if (savedChats) {
      try {
        const parsed = JSON.parse(savedChats);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed;
        }
      } catch (e) {
        console.error("Error loading chats from localStorage:", e);
      }
    }
    return [
      {
        id: 'default',
        title: 'New Legal Consultation',
        messages: [],
      }
    ];
  });

  const [activeChatId, setActiveChatId] = useState<string | null>(() => {
    const savedActiveId = localStorage.getItem('legalmind_active_chat_id');
    if (savedActiveId) return savedActiveId;
    return 'default';
  });

  const [isTyping, setIsTyping] = useState(false);
  const [previewPdfUrl, setPreviewPdfUrl] = useState<string | null>(null);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  const activeChat = chats.find((c) => c.id === activeChatId) || null;

  // Persist chats list to localStorage
  useEffect(() => {
    localStorage.setItem('legalmind_chats', JSON.stringify(chats));
  }, [chats]);

  // Persist activeChatId to localStorage
  useEffect(() => {
    if (activeChatId) {
      localStorage.setItem('legalmind_active_chat_id', activeChatId);
    } else {
      localStorage.removeItem('legalmind_active_chat_id');
    }
  }, [activeChatId]);

  // Automatically sync active chat history from backend on selection/startup
  useEffect(() => {
    if (activeChatId) {
      syncChatHistory(activeChatId);
    }
  }, [activeChatId]);

  const syncChatHistory = async (id: string) => {
    try {
      const response = await fetch(`http://localhost:8000/api/chat/${id}`);
      if (response.ok) {
        const data = await response.json();
        if (data.messages && data.messages.length > 0) {
          setChats((prev) =>
            prev.map((c) => {
              if (c.id === id) {
                return {
                  ...c,
                  messages: data.messages.map((m: any, idx: number) => ({
                    id: `${id}-${idx}`,
                    role: m.role === 'human' ? 'user' : 'ai',
                    content: m.content,
                    timestamp: new Date(),
                  })),
                };
              }
              return c;
            })
          );
        }
      }
    } catch (error) {
      console.error("Failed to sync chat history from backend:", error);
    }
  };

  const handleNewChat = () => {
    const newId = Date.now().toString();
    const newChat: Chat = {
      id: newId,
      title: `New Legal Consultation`,
      messages: [],
    };
    setChats((prev) => [newChat, ...prev]);
    setActiveChatId(newId);
    setPreviewPdfUrl(null);
  };

  const handleSelectChat = (id: string) => {
    setActiveChatId(id);
    setPreviewPdfUrl(null);
  };

  const handleGenerateMemo = async () => {
    if (!activeChat || activeChat.messages.length === 0) return;
    
    setIsGeneratingPdf(true);
    try {
      // Format chat history into a string for the backend
      const historyStr = activeChat.messages
        .map(m => `${m.role.toUpperCase()}:\n${m.content}`)
        .join('\n\n');

      const response = await fetch("http://localhost:8000/api/generate_pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          history: historyStr,
          retrieved_chunks: activeChat.retrievedChunks || []
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to generate PDF memo.");
      }

      // Read PDF as a blob
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      setPreviewPdfUrl(objectUrl);
    } catch (error) {
      console.error("Error generating memo:", error);
      alert("Error generating PDF memo. Please check the backend server.");
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  const handleSendMessage = (content: string) => {
    if (!activeChatId) return;

    // 1. Add User Message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: new Date(),
    };

    setChats((prev) =>
      prev.map((c) => {
        if (c.id === activeChatId) {
          const updatedMessages = [...c.messages, userMessage];
          // If first message, update the title to match the query
          const updatedTitle =
            c.messages.length === 0
              ? content.length > 30
                ? `${content.substring(0, 30)}...`
                : content
              : c.title;

          return {
            ...c,
            title: updatedTitle,
            messages: updatedMessages,
          };
        }
        return c;
      })
    );

    setIsTyping(true);
    fetch("http://localhost:8000/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: content,
        session_id: activeChatId,
        user_id: "lawyer_abc"
      }),
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error("Failed to communicate with the legal assistant server.");
        }
        return res.json();
      })
      .then((data) => {
        const aiMessage: Message = {
          id: Date.now().toString(),
          role: 'ai',
          content: data.response,
          timestamp: new Date(),
        };

        setChats((prev) =>
          prev.map((c) => {
            if (c.id === activeChatId) {
              const existingChunks = c.retrievedChunks || [];
              const newChunks = data.retrieved_chunks || [];
              return {
                ...c,
                messages: [...c.messages, aiMessage],
                retrievedChunks: [...existingChunks, ...newChunks]
              };
            }
            return c;
          })
        );
      })
      .catch((error) => {
        const errorMessage: Message = {
          id: Date.now().toString(),
          role: 'ai',
          content: `Error: ${error.message || "Failed to reach the backend server. Please make sure the FastAPI server is running."}`,
          timestamp: new Date(),
        };

        setChats((prev) =>
          prev.map((c) => {
            if (c.id === activeChatId) {
              return {
                ...c,
                messages: [...c.messages, errorMessage],
              };
            }
            return c;
          })
        );
      })
      .finally(() => {
        setIsTyping(false);
      });
  };

  const handleDeleteChat = async (id: string) => {
    // Remove from frontend state
    setChats((prev) => {
      const updated = prev.filter((c) => c.id !== id);
      // If we deleted the active chat, switch to the first remaining or create new
      if (activeChatId === id) {
        if (updated.length > 0) {
          setActiveChatId(updated[0].id);
        } else {
          const newId = Date.now().toString();
          const newChat: Chat = {
            id: newId,
            title: 'New Legal Consultation',
            messages: [],
          };
          setActiveChatId(newId);
          return [newChat];
        }
      }
      return updated;
    });

    // Delete from backend database
    try {
      await fetch(`http://localhost:8000/api/chat/${id}`, {
        method: 'DELETE',
      });
    } catch (error) {
      console.error('Failed to delete chat from backend:', error);
    }
  };

  const handleUpdateTitle = (newTitle: string) => {
    setChats((prev) =>
      prev.map((c) => (c.id === activeChatId ? { ...c, title: newTitle } : c))
    );
  };

  return (
    <div className={`app-container ${isSidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        isCollapsed={isSidebarCollapsed}
        onNewChat={handleNewChat}
        onSelectChat={handleSelectChat}
        onDeleteChat={handleDeleteChat}
        onToggleSidebar={() => setIsSidebarCollapsed((prev) => !prev)}
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
            onLinkClick={(url) => setPreviewPdfUrl(url)}
          />
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280' }}>
            Select a chat to begin research.
          </div>
        )}
        
        {/* PDF Preview Pane */}
        {previewPdfUrl && (
          <div className="preview-pane">
            <div className="preview-pane-header">
              <span>Formal Legal Memo Preview</span>
              <button className="preview-pane-close" onClick={() => setPreviewPdfUrl(null)} title="Close Preview">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <iframe className="preview-iframe" src={previewPdfUrl} title="Legal Memo PDF" />
          </div>
        )}
      </div>
    </div>
  );
}
