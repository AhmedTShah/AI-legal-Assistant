import { useState } from 'react';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import type { Message } from './components/MessageBubble';
import './App.css';

interface Chat {
  id: string;
  title: string;
  messages: Message[];
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
  };

  const handleSelectChat = (id: string) => {
    setActiveChatId(id);
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

    // 2. Simulate AI Typing response
    setIsTyping(true);
    setTimeout(() => {
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'ai',
        content: `I received your query: "${content}". I am reviewing the statutes and precedents database to formulate a comprehensive legal response based on Pakistani Law. (API Integration will execute here).`,
        timestamp: new Date(),
      };

      setChats((prev) =>
        prev.map((c) => {
          if (c.id === activeChatId) {
            return {
              ...c,
              messages: [...c.messages, aiMessage],
            };
          }
          return c;
        })
      );
      setIsTyping(false);
    }, 1500);
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
      {activeChat ? (
        <ChatArea
          chatTitle={activeChat.title}
          messages={activeChat.messages}
          isTyping={isTyping}
          onSendMessage={handleSendMessage}
          onUpdateTitle={handleUpdateTitle}
        />
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280' }}>
          Select a chat to begin research.
        </div>
      )}
    </div>
  );
}
