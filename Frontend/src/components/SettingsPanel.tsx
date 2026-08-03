import { useState, useEffect } from 'react';
import './SettingsPanel.css';

export interface UserSettings {
  displayName: string;
  userId: string;
  backendUrl: string;
}

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  settings: UserSettings;
  onSave: (s: UserSettings) => void;
  onClearCurrentSession: () => Promise<void>;
  onClearAllHistory: () => Promise<void>;
}

export default function SettingsPanel({
  isOpen, onClose, settings, onSave, onClearCurrentSession, onClearAllHistory,
}: SettingsPanelProps) {
  const [local, setLocal] = useState<UserSettings>(settings);
  const [saved, setSaved] = useState(false);
  const [clearing, setClearing] = useState<null | 'session' | 'all'>(null);

  useEffect(() => { setLocal(settings); }, [settings]);

  const handleSave = () => {
    onSave(local);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleClearSession = async () => {
    setClearing('session');
    await onClearCurrentSession();
    setClearing(null);
  };

  const handleClearAll = async () => {
    if (!window.confirm('Delete ALL chat history? This cannot be undone.')) return;
    setClearing('all');
    await onClearAllHistory();
    setClearing(null);
  };

  return (
    <>
      {isOpen && <div className="settings-overlay" onClick={onClose} />}
      <div className={`settings-panel ${isOpen ? 'open' : ''}`}>

        <div className="settings-header">
          <h2 className="settings-title">Settings</h2>
          <button className="settings-close" onClick={onClose} id="btn-settings-close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="settings-body">

          <p className="settings-group-label">Profile</p>

          <div className="settings-field">
            <label className="settings-label">Display Name</label>
            <input className="settings-input" value={local.displayName}
              onChange={e => setLocal(p => ({ ...p, displayName: e.target.value }))}
              placeholder="Your name" id="input-display-name" />
          </div>

          <div className="settings-field">
            <label className="settings-label">User ID</label>
            <p className="settings-hint">Controls which long-term memory is loaded. Change when switching users.</p>
            <input className="settings-input" value={local.userId}
              onChange={e => setLocal(p => ({ ...p, userId: e.target.value }))}
              placeholder="lawyer_abc" id="input-user-id" />
          </div>

          <p className="settings-group-label">Connection</p>

          <div className="settings-field">
            <label className="settings-label">Backend URL</label>
            <p className="settings-hint">Change to a deployed server address for production use.</p>
            <input className="settings-input" value={local.backendUrl}
              onChange={e => setLocal(p => ({ ...p, backendUrl: e.target.value }))}
              placeholder="http://localhost:8000" id="input-backend-url" />
          </div>

          <button className={`settings-save-btn ${saved ? 'saved' : ''}`} onClick={handleSave} id="btn-save-settings">
            {saved ? '✓  Saved' : 'Save Changes'}
          </button>

          <p className="settings-group-label">Data</p>

          <div className="settings-field">
            <label className="settings-label">Clear Current Session</label>
            <p className="settings-hint">Deletes all messages in the active chat from the database.</p>
            <button className="settings-danger-btn" onClick={handleClearSession}
              disabled={clearing !== null} id="btn-clear-session">
              {clearing === 'session' ? 'Clearing...' : 'Clear Session'}
            </button>
          </div>

          <div className="settings-field">
            <label className="settings-label">Clear All History</label>
            <p className="settings-hint">Permanently deletes every chat session and all messages.</p>
            <button className="settings-danger-btn danger-red" onClick={handleClearAll}
              disabled={clearing !== null} id="btn-clear-all">
              {clearing === 'all' ? 'Clearing...' : 'Clear All History'}
            </button>
          </div>

        </div>

        <div className="settings-footer">
          LegalMind v1.0&nbsp;&nbsp;·&nbsp;&nbsp;AI Legal Research for Pakistani Law
        </div>
      </div>
    </>
  );
}
