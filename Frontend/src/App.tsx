import { useState } from 'react';
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
  const [chats, setChats] = useState<Chat[]>([
    {
      id: '1',
      title: 'Section 302 PPC Punishments',
      messages: [
        {
          id: '1-1',
          role: 'user',
          content: 'What is the punishment under Section 302 PPC?',
          timestamp: new Date(),
        },
        {
          id: '1-2',
          role: 'ai',
          content: 'Under Section 302 of the Pakistan Penal Code (PPC), the punishment for Qatl-i-Amd (deliberate murder) is: \n\n1. Death (Tazir/Qisas)\n2. Imprisonment for life as Tazir having regard to the facts and circumstances of the case.\n\nThe court will determine the specific application based on evidence and whether standard proof requirements for Qisas are met.',
          timestamp: new Date(),
        },
      ],
    },
    {
      id: '2',
      title: 'Cybercrime under PECA 2016',
      messages: [
        {
          id: '2-1',
          role: 'user',
          content: 'Is cyber stalking bailable under PECA 2016?',
          timestamp: new Date(),
        },
        {
          id: '2-2',
          role: 'ai',
          content: 'Under Section 24 of the Prevention of Electronic Crimes Act (PECA) 2016, cyber stalking is defined. Section 43 of PECA outlines bail provisions. Cyber stalking is a non-bailable offence, which means bail cannot be claimed as a matter of right and is subject to judicial discretion.',
          timestamp: new Date(),
        },
      ],
    },
  ]);

  const [activeChatId, setActiveChatId] = useState<string | null>('1');
  const [isTyping, setIsTyping] = useState(false);
  const [previewPdfUrl, setPreviewPdfUrl] = useState<string | null>(null);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);

  const activeChat = chats.find((c) => c.id === activeChatId) || null;

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

    // 2. Fetch AI Response from FastAPI Backend
    setIsTyping(true);
    fetch("http://localhost:8000/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: content }),
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

  const handleUpdateTitle = (newTitle: string) => {
    setChats((prev) =>
      prev.map((c) => (c.id === activeChatId ? { ...c, title: newTitle } : c))
    );
  };

  return (
    <div className="app-container">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onNewChat={handleNewChat}
        onSelectChat={handleSelectChat}
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
