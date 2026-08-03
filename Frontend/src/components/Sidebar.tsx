import './Sidebar.css';
import lawLogo from '../assets/law-logo.png';

interface Chat {
  id: string;
  title: string;
}

interface SidebarProps {
  chats: Chat[];
  activeChatId: string | null;
  isCollapsed: boolean;
  onNewChat: () => void;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onToggleSidebar: () => void;
}

export default function Sidebar({ chats, activeChatId, isCollapsed, onNewChat, onSelectChat, onDeleteChat, onToggleSidebar }: SidebarProps) {
  return (
    <aside className={`sidebar ${isCollapsed ? 'collapsed' : ''}`}>
      {/* ── Logo & Sidebar Toggle ─────────────────────── */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <img className="sidebar-logo-img" src={lawLogo} alt="LegalMind Logo" />
          {!isCollapsed && <span className="sidebar-logo-text">LegalMind</span>}
        </div>
        <button className="sidebar-toggle-btn" aria-label="Toggle Sidebar" id="btn-toggle-sidebar" onClick={onToggleSidebar}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        </button>
      </div>

      {/* ── New Chat Button ── */}
      <button className="sidebar-new-chat" onClick={onNewChat} id="btn-new-chat" title="New Chat">
        <svg className="new-chat-plus" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        {!isCollapsed && 'New Chat'}
      </button>

      {/* ── Navigation ──────────────── */}
      {!isCollapsed && (
        <nav className="sidebar-nav">
          <button className="sidebar-nav-item" id="nav-explore">
            <svg className="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            Explore
          </button>
          
          <button className="sidebar-nav-item" id="nav-categories">
            <svg className="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
            </svg>
            Categories
          </button>

          <button className="sidebar-nav-item" id="nav-library">
            <svg className="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            Library
            <span className="sidebar-library-badge">32</span>
          </button>

          <button className="sidebar-nav-item" id="nav-settings">
            <svg className="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            Settings
          </button>
        </nav>
      )}

      {/* ── Recent Chats ─────── */}
      {!isCollapsed && (
        <>
          <div className="sidebar-section-label">Recent Chats</div>
          <div className="sidebar-chats dark-scrollbar">
            {chats.length === 0 && (
              <div className="sidebar-chat-item-empty">
                No consultations yet
              </div>
            )}
            {chats.map((chat) => (
              <div
                key={chat.id}
                className={`sidebar-chat-item ${activeChatId === chat.id ? 'active' : ''}`}
                onClick={() => onSelectChat(chat.id)}
                id={`chat-${chat.id}`}
              >
                <span className="sidebar-chat-title">{chat.title}</span>
                <button
                  className="sidebar-chat-delete"
                  title="Delete chat"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteChat(chat.id);
                  }}
                  id={`delete-chat-${chat.id}`}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    <line x1="10" y1="11" x2="10" y2="17" />
                    <line x1="14" y1="11" x2="14" y2="17" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── User Profile ──────────────────────────────── */}
      <div className="sidebar-user">
        <img 
          className="sidebar-user-avatar" 
          src="https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&q=80&w=120&h=120" 
          alt="Maya Johnes" 
        />
        {!isCollapsed && (
          <div className="sidebar-user-info">
            <span className="sidebar-user-name">Maya Johnes</span>
          </div>
        )}
        {!isCollapsed && (
          <button className="sidebar-notification-btn" aria-label="Notifications" id="btn-notifications">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
          </button>
        )}
      </div>
    </aside>
  );
}
