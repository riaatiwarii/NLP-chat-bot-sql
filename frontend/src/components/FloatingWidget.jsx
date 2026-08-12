import React, { useState, useRef, useEffect } from 'react';
import { MessageSquare, X, Send, Shield, Bot, User, Sparkles, Minimize2, Maximize2, RotateCcw } from 'lucide-react';

export default function FloatingWidget({ gatewayUrl = '', initialOpen = false, theme = 'dark', position = 'bottom-right', apiKey = '' }) {
  const [isOpen, setIsOpen] = useState(initialOpen);
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "Hello! I am your **SBI CMS Intelligence Assistant**. How can I assist with surveillance telemetry, active alerts, or branch operations today?"
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [chatContext, setChatContext] = useState({});
  const [isExpanded, setIsExpanded] = useState(false);
  const messagesEndRef = useRef(null);

  const suggestions = [
    "List the LHOs",
    "Show today's dashboard summary",
    "Which branch has the highest number of alerts?",
    "Which CCTV cameras are offline?",
    "Show the 5 most recent high-severity alerts in Noida"
  ];

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
    }
  }, [messages, isTyping, isOpen]);

  const handleSend = async (textToSend) => {
    const query = textToSend || input;
    if (!query || !query.trim()) return;

    const userMsg = { role: 'user', content: query.trim() };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput('');
    setIsTyping(true);

    try {
      const endpoint = gatewayUrl ? `${gatewayUrl.replace(/\/$/, '')}/api/chat` : '/api/chat';
      const headers = { 'Content-Type': 'application/json' };
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`;
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          message: query.trim(),
          history: updatedMessages,
          context: chatContext
        })
      });


      if (response.ok) {
        const data = await response.json();
        setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
        if (data.context) {
          setChatContext(data.context);
        }
      } else {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: "**Error**: Unable to reach the central monitoring gateway. Please verify your connection."
        }]);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `**Connection Error**: Failed to connect to Central Gateway (${err.message}).`
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const resetChat = () => {
    setMessages([
      {
        role: 'assistant',
        content: "Chat session refreshed. How can I assist with your central surveillance queries?"
      }
    ]);
    setChatContext({});
  };

  // Robust markdown table renderer
  const renderMessageContent = (text) => {
    const lines = text.split('\n');
    const elements = [];
    let tableBuffer = [];
    let key = 0;

    const flushTable = () => {
      if (tableBuffer.length === 0) return;
      const rows = tableBuffer.filter(row => !row.replace(/\s/g, '').includes('|---|'));
      if (rows.length === 0) {
        tableBuffer = [];
        return;
      }

      const parsedRows = rows.map(row => {
        const parts = row.split('|').map(p => p.trim());
        if (row.startsWith('|')) parts.shift();
        if (row.endsWith('|')) parts.pop();
        return parts;
      });

      if (parsedRows.length > 0) {
        const headers = parsedRows[0];
        const bodyRows = parsedRows.slice(1);

        elements.push(
          <div className="plugin-table-container" key={`tbl-${key++}`}>
            <table className="plugin-table">
              <thead>
                <tr>
                  {headers.map((h, i) => (
                    <th key={`th-${i}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bodyRows.map((r, ri) => (
                  <tr key={`tr-${ri}`}>
                    {r.map((td, tdi) => (
                      <td key={`td-${tdi}`}>{td}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      tableBuffer = [];
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes('|') && (line.startsWith('|') || line.endsWith('|') || line.trim().startsWith('|'))) {
        tableBuffer.push(line);
      } else {
        flushTable();
        if (!line.trim()) {
          elements.push(<div key={`sp-${key++}`} style={{ height: '6px' }} />);
          continue;
        }

        // Header formatting
        if (line.startsWith('### ')) {
          elements.push(<h4 key={`h3-${key++}`} className="plugin-heading-3">{line.replace('### ', '')}</h4>);
        } else if (line.startsWith('## ')) {
          elements.push(<h3 key={`h2-${key++}`} className="plugin-heading-2">{line.replace('## ', '')}</h3>);
        } else if (line.startsWith('- ') || line.startsWith('* ')) {
          const content = line.substring(2);
          elements.push(
            <li key={`li-${key++}`} className="plugin-list-item">
              <span dangerouslySetInnerHTML={{ __html: formatInline(content) }} />
            </li>
          );
        } else if (/^\d+\.\s/.test(line)) {
          const content = line.replace(/^\d+\.\s/, '');
          elements.push(
            <div key={`ol-${key++}`} className="plugin-list-item">
              <span className="plugin-num-badge">{line.match(/^\d+/)[0]}</span>
              <span dangerouslySetInnerHTML={{ __html: formatInline(content) }} />
            </div>
          );
        } else {
          elements.push(
            <p key={`p-${key++}`} className="plugin-paragraph" dangerouslySetInnerHTML={{ __html: formatInline(line) }} />
          );
        }
      }
    }
    flushTable();
    return elements;
  };

  const formatInline = (str) => {
    return str
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code class="plugin-inline-code">$1</code>');
  };

  return (
    <div className={`sbi-cms-widget-wrapper ${position} theme-${theme}`}>

      {/* Floating Launcher Button */}
      {!isOpen && (
        <button
          className="sbi-cms-launcher-btn"
          onClick={() => setIsOpen(true)}
          title="Open SBI CMS AI Operations Assistant"
        >
          <div className="sbi-cms-launcher-glow"></div>
          <Shield className="sbi-cms-launcher-icon" size={26} />
          <span className="sbi-cms-launcher-pulse"></span>
        </button>
      )}

      {/* Floating Chat Modal */}
      {isOpen && (
        <div className={`sbi-cms-popup-container ${isExpanded ? 'expanded' : ''}`}>
          {/* Header */}
          <div className="sbi-cms-popup-header">
            <div className="sbi-cms-popup-brand">
              <div className="sbi-cms-brand-icon">
                <Shield size={18} />
              </div>
              <div>
                <div className="sbi-cms-brand-title">SBI CMS Intelligence</div>
                <div className="sbi-cms-brand-subtitle">
                  <span className="sbi-cms-status-dot"></span> Central Gateway Active
                </div>
              </div>
            </div>
            <div className="sbi-cms-popup-controls">
              <button onClick={resetChat} title="Reset Chat" className="sbi-cms-control-btn">
                <RotateCcw size={15} />
              </button>
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                title={isExpanded ? "Collapse" : "Expand"}
                className="sbi-cms-control-btn"
              >
                {isExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              </button>
              <button onClick={() => setIsOpen(false)} title="Close" className="sbi-cms-control-btn close">
                <X size={17} />
              </button>
            </div>
          </div>

          {/* Messages Body */}
          <div className="sbi-cms-popup-body">
            {messages.map((m, idx) => (
              <div key={idx} className={`sbi-cms-msg-row ${m.role}`}>
                <div className={`sbi-cms-msg-avatar ${m.role}`}>
                  {m.role === 'assistant' ? <Bot size={14} /> : <User size={14} />}
                </div>
                <div className={`sbi-cms-msg-bubble ${m.role}`}>
                  {m.role === 'assistant' ? renderMessageContent(m.content) : m.content}
                </div>
              </div>
            ))}
            {isTyping && (
              <div className="sbi-cms-msg-row assistant">
                <div className="sbi-cms-msg-avatar assistant">
                  <Bot size={14} />
                </div>
                <div className="sbi-cms-msg-bubble assistant typing">
                  <span className="sbi-cms-typing-dot"></span>
                  <span className="sbi-cms-typing-dot"></span>
                  <span className="sbi-cms-typing-dot"></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Suggestion Chips */}
          <div className="sbi-cms-suggestions-container">
            <div className="sbi-cms-suggestions-scroll">
              {suggestions.map((sug, i) => (
                <button
                  key={i}
                  className="sbi-cms-chip"
                  onClick={() => handleSend(sug)}
                >
                  <Sparkles size={11} className="sbi-cms-chip-icon" />
                  {sug}
                </button>
              ))}
            </div>
          </div>

          {/* Input Footer */}
          <form className="sbi-cms-popup-footer" onSubmit={(e) => { e.preventDefault(); handleSend(); }}>
            <input
              type="text"
              className="sbi-cms-popup-input"
              placeholder="Ask central telemetry, branches, or alerts..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isTyping}
            />
            <button
              type="submit"
              className="sbi-cms-send-btn"
              disabled={!input.trim() || isTyping}
            >
              <Send size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
