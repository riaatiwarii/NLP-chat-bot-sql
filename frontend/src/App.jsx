import React, { useState, useEffect } from 'react';
import { Shield, Settings as SettingsIcon, AlertCircle, RefreshCw, LayoutDashboard, MessageSquare } from 'lucide-react';
import Dashboard from './components/Dashboard';
import Chatbot from './components/Chatbot';
import Settings from './components/Settings';
import FloatingWidget from './components/FloatingWidget';

export default function App() {
  const [viewMode, setViewMode] = useState('dashboard'); // 'dashboard' or 'widget_preview'
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [dashboardData, setDashboardData] = useState(null);
  const [healthData, setHealthData] = useState(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  
  // Ollama execution toggle (default to false for instant local rule engine)
  const [useOllama, setUseOllama] = useState(false);
  
  // Conversation session state with persistent session_id
  const [chatContext, setChatContext] = useState({});
  const [sessionId, setSessionId] = useState(() => {
    // Initialize session_id from localStorage or generate new one
    const saved = localStorage.getItem('sbi_cms_session_id');
    return saved || 'session_' + Date.now();
  });

  const fetchDashboard = async () => {
    try {
      const response = await fetch('/api/dashboard');
      if (response.ok) {
        const data = await response.json();
        setDashboardData(data);
      }
    } catch (err) {
      console.error("Error fetching dashboard data:", err);
    }
  };

  const fetchHealth = async (isInitial = false) => {
    try {
      const response = await fetch('/api/health');
      if (response.ok) {
        const data = await response.json();
        setHealthData(data);
        if (isInitial && data.ollama && data.ollama.connected) {
          setUseOllama(true);
        }
      }
    } catch (err) {
      console.error("Error fetching health status:", err);
    }
  };

  useEffect(() => {
    fetchDashboard();
    fetchHealth(true);
    // Poll dashboard data every 12 seconds
    const interval = setInterval(() => {
      fetchDashboard();
      fetchHealth(false);
    }, 12000);
    return () => clearInterval(interval);
  }, []);

  const handleSendMessage = async (text) => {
    const newMsg = { role: 'user', content: text };
    const updatedMessages = [...messages, newMsg];
    setMessages(updatedMessages);
    setIsTyping(true);

    // Merge settings into chat request context
    const contextToSend = {
      ...chatContext,
      use_ollama: useOllama
    };

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          history: updatedMessages,
          context: contextToSend
        })
      });

      if (response.ok) {
        const data = await response.json();
        setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
        // Keep context returned from server and update session_id if provided
        setChatContext(data.context);
        if (data.session_id && data.session_id !== sessionId) {
          setSessionId(data.session_id);
          localStorage.setItem('sbi_cms_session_id', data.session_id);
        }
      } else {
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: "**Error**: Failed to retrieve a response from the operations backend." 
        }]);
      }
    } catch (err) {
      console.error("Chat error:", err);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `**Error**: The backend server is unreachable. Check if FastAPI is running.\n\nDetails: ${err.message}` 
      }]);
    } finally {
      setIsTyping(false);
      fetchDashboard();
    }
  };

  const handleCardClick = (prompt) => {
    handleSendMessage(prompt);
  };

  const handleSaveSettings = (host, model, enableOllama) => {
    setUseOllama(enableOllama);
    // Persist local selection in context
    setChatContext(prev => ({
      ...prev,
      use_ollama: enableOllama
    }));
  };

  const isOllamaConnected = healthData?.ollama?.connected || false;
  const activeModel = healthData?.ollama?.configured_model || 'sqlcoder:15b';

  return (
    <div className="app-container">
      {/* Central Header */}
      <header className="header">
        <div className="header-brand">
          <Shield className="header-logo" size={24} style={{ color: 'var(--sbi-blue-light)' }} />
          <div className="header-title-container">
            <h1 className="header-title" style={{ fontSize: '1.05rem' }}>SBI Centralized Monitoring System</h1>
            <h2 className="header-subtitle" style={{ fontSize: '0.68rem' }}>Central Gateway & Intelligence Operations</h2>
          </div>
        </div>

        <div className="header-controls">
          {/* Mode Switcher */}
          <div style={{ display: 'flex', background: 'rgba(255,255,255,0.06)', borderRadius: '8px', padding: '2px', border: '1px solid rgba(255,255,255,0.1)' }}>
            <button
              onClick={() => setViewMode('dashboard')}
              style={{
                background: viewMode === 'dashboard' ? 'var(--sbi-accent)' : 'transparent',
                color: viewMode === 'dashboard' ? '#fff' : 'var(--text-secondary)',
                border: 'none',
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.74rem',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              <LayoutDashboard size={13} />
              Full Dashboard
            </button>
            <button
              onClick={() => setViewMode('widget_preview')}
              style={{
                background: viewMode === 'widget_preview' ? 'var(--sbi-accent)' : 'transparent',
                color: viewMode === 'widget_preview' ? '#fff' : 'var(--text-secondary)',
                border: 'none',
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.74rem',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              <MessageSquare size={13} />
              Plugin Widget Preview
            </button>
          </div>

          <div className="system-status" style={{ padding: '4px 10px', fontSize: '0.75rem' }}>
            <div className="status-dot"></div>
            <span>Central Gateway Active</span>
          </div>

          <button onClick={() => setIsSettingsOpen(true)} className="btn-settings" title="Open Configurations" style={{ width: '32px', height: '32px' }}>
            <SettingsIcon size={15} />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      {viewMode === 'dashboard' ? (
        <main className="layout-content">
          {/* Left Side: Live Operational Dashboard */}
          <Dashboard 
            dashboardData={dashboardData} 
            onRefresh={fetchDashboard}
            onCardClick={handleCardClick}
          />

          {/* Right Side: Operations Bot assistant */}
          <Chatbot 
            messages={messages} 
            onSendMessage={handleSendMessage}
            isTyping={isTyping}
            ollamaActive={useOllama && isOllamaConnected}
            ollamaModel={activeModel}
            onSelectSuggestion={handleSendMessage}
          />
        </main>
      ) : (
        /* Widget Plugin Preview Mode */
        <div style={{ flex: 1, padding: '32px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'radial-gradient(circle at center, #1e293b 0%, #07090e 100%)', position: 'relative' }}>
          <div style={{ maxWidth: '680px', textAlign: 'center', background: 'rgba(15, 23, 42, 0.75)', border: '1px solid rgba(255,255,255,0.1)', padding: '36px', borderRadius: '16px', backdropFilter: 'blur(12px)', boxShadow: '0 20px 40px rgba(0,0,0,0.6)' }}>
            <div style={{ width: '56px', height: '56px', borderRadius: '14px', background: 'rgba(2, 132, 199, 0.15)', border: '1px solid rgba(2, 132, 199, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', color: '#38bdf8' }}>
              <Shield size={28} />
            </div>
            <h2 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>SBI CMS Floating Widget Plugin</h2>
            <p style={{ color: '#94a3b8', fontSize: '0.88rem', lineHeight: '1.6', marginBottom: '24px' }}>
              This mode demonstrates the **Embeddable Chatbot Plugin**. Any external portal or internal web page in the bank can embed this assistant by adding one simple script tag.
            </p>
            <div style={{ background: '#090e17', padding: '14px 18px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)', textAlign: 'left', fontFamily: 'monospace', fontSize: '0.78rem', color: '#38bdf8', overflowX: 'auto', marginBottom: '20px' }}>
              <code>&lt;script src="http://localhost:8001/plugin/widget.js" data-sbi-cms-gateway="http://localhost:8001"&gt;&lt;/script&gt;</code>
            </div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: 'rgba(74, 222, 128, 0.1)', border: '1px solid rgba(74, 222, 128, 0.25)', padding: '6px 14px', borderRadius: '20px', color: '#4ade80', fontSize: '0.8rem' }}>
              <span>👉 Click the floating shield badge in the bottom-right corner to test the widget!</span>
            </div>
          </div>

          {/* Floating Widget Instance in Preview Mode */}
          <FloatingWidget gatewayUrl="" initialOpen={true} />
        </div>
      )}

      {/* Configuration modal */}
      <Settings 
        isOpen={isSettingsOpen} 
        onClose={() => setIsSettingsOpen(false)}
        onSave={handleSaveSettings}
        healthData={healthData}
        fetchHealth={fetchHealth}
        currentUseOllama={useOllama}
      />
    </div>
  );
}
