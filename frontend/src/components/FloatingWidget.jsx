import React, { useState, useRef, useEffect } from 'react';
import { MessageSquare, X, Send, Shield, Bot, User, Sparkles, Minimize2, Maximize2, RotateCcw, ThumbsUp, ThumbsDown, Check } from 'lucide-react';

export default function FloatingWidget({ gatewayUrl = '', initialOpen = false, theme = 'dark', position = 'bottom-right', apiKey = '' }) {
  const [isOpen, setIsOpen] = useState(initialOpen);
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([
    {
      id: 'msg-init',
      role: 'assistant',
      content: "Hello! I am your **Production Text-to-SQL Intelligence Assistant**. How can I assist with surveillance telemetry, active alerts, or branch operations today?"
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  
  // Feedback modal state
  const [feedbackModal, setFeedbackModal] = useState({ open: false, msgObj: null });
  const [correctedSqlInput, setCorrectedSqlInput] = useState('');
  const [aliasKeyInput, setAliasKeyInput] = useState('');
  const [aliasValInput, setAliasValInput] = useState('');
  const [correctionType, setCorrectionType] = useState('logic');
  const [feedbackSent, setFeedbackSent] = useState({});

  const messagesEndRef = useRef(null);

  const getEffectiveGatewayUrl = () => {
    if (gatewayUrl && gatewayUrl.trim()) return gatewayUrl.replace(/\/$/, '');
    if (typeof window !== 'undefined' && window.location && window.location.protocol.startsWith('http')) {
      return window.location.origin;
    }
    return 'http://localhost:8001';
  };

  const suggestions = [
    "List the LHOs",
    "Show today's dashboard summary",
    "Which branch has the highest number of alerts?",
    "Which CCTV cameras are offline?",
    "Show recent high severity alerts in Noida"
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

    const userMsg = { id: `msg-${Date.now()}-user`, role: 'user', content: query.trim() };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput('');
    setIsTyping(true);

    try {
      const baseUrl = getEffectiveGatewayUrl();
      const endpoint = `${baseUrl}/api/chat`;
      const headers = { 'Content-Type': 'application/json' };
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`;
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          message: query.trim(),
          session_id: sessionId || undefined,
          history: updatedMessages
        })
      });

      if (response.ok) {
        const data = await response.json();
        if (data.session_id) {
          setSessionId(data.session_id);
        }
        const assistantMsg = {
          id: `msg-${Date.now()}-ast`,
          role: 'assistant',
          content: data.response,
          sql: data.sql,
          plan: data.plan,
          confidence_score: data.confidence_score,
          is_abstention: data.is_abstention,
          question: query.trim()
        };
        setMessages(prev => [...prev, assistantMsg]);
      } else {
        setMessages(prev => [...prev, {
          id: `msg-${Date.now()}-err`,
          role: 'assistant',
          content: `**Error**: Unable to reach central gateway API at \`${baseUrl}\`. Please check server connection.`
        }]);
      }
    } catch (err) {
      const baseUrl = getEffectiveGatewayUrl();
      setMessages(prev => [...prev, {
        id: `msg-${Date.now()}-err`,
        role: 'assistant',
        content: `**Connection Error**: Failed to connect to Central Gateway at \`${baseUrl}\` (${err.message}).`
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const submitFeedback = async (msg, rating, customCorrectedSql = null) => {
    if (!msg) return;
    try {
      const baseUrl = getEffectiveGatewayUrl();
      const endpoint = `${baseUrl}/api/feedback`;
      const headers = { 'Content-Type': 'application/json' };
      if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

      await fetch(endpoint, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          session_id: sessionId,
          question: msg.question || 'Query',
          rating: rating,
          generated_sql: msg.sql,
          corrected_sql: customCorrectedSql || msg.sql,
          correction_type: correctionType,
          alias_key: aliasKeyInput,
          alias_canonical: aliasValInput
        })
      });

      setFeedbackSent(prev => ({ ...prev, [msg.id]: rating }));
      setFeedbackModal({ open: false, msgObj: null });
      setCorrectedSqlInput('');
      setAliasKeyInput('');
      setAliasValInput('');
    } catch (err) {
      console.error('Feedback submit error:', err);
    }
  };

  const resetChat = () => {
    setMessages([
      {
        id: 'msg-init-reset',
        role: 'assistant',
        content: "Chat session refreshed. How can I assist with your central surveillance queries?"
      }
    ]);
    setSessionId('');
    setFeedbackSent({});
  };

  // Markdown table renderer
  const renderMessageContent = (text) => {
    if (!text) return null;
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
        if (line.trim()) {
          const formatted = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
          elements.push(
            <p key={`p-${key++}`} dangerouslySetInnerHTML={{ __html: formatted }} style={{ marginBottom: '6px', lineHeight: '1.45' }} />
          );
        }
      }
    }
    flushTable();

    return elements;
  };

  const posClass = position === 'bottom-left' ? 'bottom-left' : '';

  return (
    <div className={`sbi-cms-widget-wrapper ${posClass}`}>
      {/* Floating Trigger Launcher Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="sbi-cms-launcher-btn"
          title="Open Text-to-SQL Assistant"
        >
          <div className="sbi-cms-launcher-pulse" />
          <Bot style={{ width: '28px', height: '28px' }} />
        </button>
      )}

      {/* Main Chat Popup Container */}
      {isOpen && (
        <div className={`sbi-cms-popup-container ${isExpanded ? 'expanded' : ''}`}>
          {/* Header */}
          <div className="sbi-cms-popup-header">
            <div className="sbi-cms-popup-brand">
              <div className="sbi-cms-brand-icon">
                <Shield style={{ width: '20px', height: '20px' }} />
              </div>
              <div>
                <div className="sbi-cms-brand-title">Text-to-SQL Intelligence</div>
                <div className="sbi-cms-brand-subtitle">
                  <span className="sbi-cms-status-dot" />
                  16-Stage Self-Hosted Gateway
                </div>
              </div>
            </div>
            <div className="sbi-cms-popup-controls">
              <button onClick={resetChat} title="Reset Chat" className="sbi-cms-control-btn">
                <RotateCcw style={{ width: '16px', height: '16px' }} />
              </button>
              <button onClick={() => setIsExpanded(!isExpanded)} title={isExpanded ? "Collapse" : "Expand"} className="sbi-cms-control-btn">
                {isExpanded ? <Minimize2 style={{ width: '16px', height: '16px' }} /> : <Maximize2 style={{ width: '16px', height: '16px' }} />}
              </button>
              <button onClick={() => setIsOpen(false)} title="Close" className="sbi-cms-control-btn close">
                <X style={{ width: '18px', height: '18px' }} />
              </button>
            </div>
          </div>

          {/* Messages Body */}
          <div className="sbi-cms-popup-body">
            {messages.map((msg) => (
              <div key={msg.id} className={`sbi-cms-msg-row ${msg.role}`}>
                <div className={`sbi-cms-msg-avatar ${msg.role}`}>
                  {msg.role === 'assistant' ? <Bot style={{ width: '15px', height: '15px' }} /> : <User style={{ width: '15px', height: '15px' }} />}
                </div>
                <div className={`sbi-cms-msg-bubble ${msg.role}`}>
                  {renderMessageContent(msg.content)}

                  {/* Generated SQL preview if present */}
                  {msg.sql && (
                    <div style={{ marginTop: '8px', padding: '8px', background: '#090e17', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.08)', fontFamily: 'monospace', fontSize: '0.75rem', color: '#38bdf8', overflowX: 'auto' }}>
                      <div style={{ fontSize: '0.65rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 'bold', marginBottom: '4px' }}>Generated SQL</div>
                      <code>{msg.sql}</code>
                    </div>
                  )}

                  {/* Feedback 👍 / 👎 buttons for Assistant responses */}
                  {msg.role === 'assistant' && msg.id !== 'msg-init' && (
                    <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.72rem', color: '#94a3b8' }}>
                      <span>Accurate response?</span>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        {feedbackSent[msg.id] ? (
                          <span style={{ color: '#4ade80', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <Check style={{ width: '14px', height: '14px' }} /> Feedback saved
                          </span>
                        ) : (
                          <>
                            <button
                              onClick={() => submitFeedback(msg, 'thumbs_up')}
                              style={{ background: 'transparent', border: 'none', color: '#4ade80', cursor: 'pointer', padding: '2px 4px' }}
                              title="Helpful / Correct SQL"
                            >
                              <ThumbsUp style={{ width: '14px', height: '14px' }} />
                            </button>
                            <button
                              onClick={() => setFeedbackModal({ open: true, msgObj: msg })}
                              style={{ background: 'transparent', border: 'none', color: '#f87171', cursor: 'pointer', padding: '2px 4px' }}
                              title="Incorrect / Submit Analyst Correction"
                            >
                              <ThumbsDown style={{ width: '14px', height: '14px' }} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="sbi-cms-msg-row assistant">
                <div className="sbi-cms-msg-avatar assistant">
                  <Bot style={{ width: '15px', height: '15px' }} />
                </div>
                <div className="sbi-cms-msg-bubble assistant typing">
                  <div className="sbi-cms-typing-dot" />
                  <div className="sbi-cms-typing-dot" />
                  <div className="sbi-cms-typing-dot" />
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Suggestions Scrollbar */}
          <div className="sbi-cms-suggestions-container">
            <div className="sbi-cms-suggestions-scroll">
              {suggestions.map((s, i) => (
                <div key={i} className="sbi-cms-chip" onClick={() => handleSend(s)}>
                  <Sparkles style={{ width: '12px', height: '12px' }} />
                  {s}
                </div>
              ))}
            </div>
          </div>

          {/* Footer Input Form */}
          <form className="sbi-cms-popup-footer" onSubmit={(e) => { e.preventDefault(); handleSend(); }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask surveillance, camera status, or branch metrics..."
              className="sbi-cms-popup-input"
            />
            <button type="submit" disabled={!input.trim() || isTyping} className="sbi-cms-send-btn">
              <Send style={{ width: '15px', height: '15px' }} />
            </button>
          </form>

          {/* Analyst Feedback Modal */}
          {feedbackModal.open && feedbackModal.msgObj && (
            <div style={{ position: 'absolute', inset: 0, background: 'rgba(9, 14, 23, 0.92)', backdropFilter: 'blur(4px)', zIndex: 100, padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '12px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', boxShadow: '0 20px 40px rgba(0,0,0,0.8)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 'bold', fontSize: '0.85rem', color: '#f8fafc' }}>Submit Analyst Correction</span>
                  <button onClick={() => setFeedbackModal({ open: false, msgObj: null })} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>
                    <X style={{ width: '16px', height: '16px' }} />
                  </button>
                </div>
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                  Question: <span style={{ color: '#cbd5e1', fontStyle: 'italic' }}>"{feedbackModal.msgObj.question}"</span>
                </div>

                <div style={{ display: 'flex', gap: '16px', fontSize: '0.75rem', color: '#cbd5e1' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                    <input type="radio" name="corrType" checked={correctionType === 'logic'} onChange={() => setCorrectionType('logic')} />
                    SQL Logic Correction
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                    <input type="radio" name="corrType" checked={correctionType === 'value'} onChange={() => setCorrectionType('value')} />
                    Value Alias Correction
                  </label>
                </div>

                {correctionType === 'logic' ? (
                  <div>
                    <label style={{ display: 'block', fontSize: '0.72rem', color: '#cbd5e1', marginBottom: '4px' }}>Correct SQL Query:</label>
                    <textarea
                      rows={3}
                      value={correctedSqlInput}
                      onChange={(e) => setCorrectedSqlInput(e.target.value)}
                      placeholder={feedbackModal.msgObj.sql || "SELECT ... FROM ..."}
                      style={{ width: '100%', background: '#090e17', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '6px', padding: '8px', fontSize: '0.75rem', fontFamily: 'monospace', color: '#38bdf8', outline: 'none' }}
                    />
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.72rem', color: '#cbd5e1' }}>User Mention / Abbreviation (e.g. "del"):</label>
                      <input
                        type="text"
                        value={aliasKeyInput}
                        onChange={(e) => setAliasKeyInput(e.target.value)}
                        placeholder="del"
                        style={{ width: '100%', background: '#090e17', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '6px', padding: '6px', fontSize: '0.75rem', color: '#fff' }}
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.72rem', color: '#cbd5e1' }}>Canonical DB Value (e.g. "New Delhi"):</label>
                      <input
                        type="text"
                        value={aliasValInput}
                        onChange={(e) => setAliasValInput(e.target.value)}
                        placeholder="New Delhi"
                        style={{ width: '100%', background: '#090e17', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '6px', padding: '6px', fontSize: '0.75rem', color: '#fff' }}
                      />
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', paddingTop: '4px' }}>
                  <button
                    onClick={() => setFeedbackModal({ open: false, msgObj: null })}
                    style={{ background: '#1e293b', border: 'none', color: '#cbd5e1', padding: '6px 12px', borderRadius: '6px', fontSize: '0.75rem', cursor: 'pointer' }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => submitFeedback(feedbackModal.msgObj, 'thumbs_down', correctedSqlInput)}
                    style={{ background: '#f87171', border: 'none', color: '#fff', padding: '6px 12px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: 'bold', cursor: 'pointer' }}
                  >
                    Save Correction
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
