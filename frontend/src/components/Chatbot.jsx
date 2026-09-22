import React, { useState, useRef, useEffect } from 'react';
import { Send, Shield, User, Bot, Sparkles, MessageSquare } from 'lucide-react';

export default function Chatbot({ messages, onSendMessage, isTyping, ollamaActive, ollamaModel, onSelectSuggestion }) {
  const [input, setInput] = useState('');
  const logEndRef = useRef(null);

  const suggestions = [
    "Show today's dashboard summary",
    "Tell me about alertID 93527",
    "Which branch has the highest number of alerts?",
    "Show recent high severity alerts in Noida",
    "List the LHOs",
    "Show unresolved alerts"
  ];

  const scrollToBottom = () => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input || !input.trim()) return;
    onSendMessage(input.trim());
    setInput('');
  };

  const handleSuggestionClick = (sug) => {
    onSelectSuggestion(sug);
  };

  // Simple, robust parser for formatting operations-analyst Markdown responses
  const renderMessageContent = (text) => {
    const lines = text.split('\n');
    const elements = [];
    let tableBuffer = [];
    let key = 0;

    const flushTable = () => {
      if (tableBuffer.length === 0) return;
      
      // Filter out markdown separator line (e.g., |---|---|)
      const rows = tableBuffer.filter(row => !row.replace(/\s/g, '').includes('|---|'));
      if (rows.length === 0) {
        tableBuffer = [];
        return;
      }
      
      const parsedRows = rows.map(row => {
        // Split by '|' and trim elements, discarding first and last empty elements from border pipes
        const parts = row.split('|').map(p => p.trim());
        if (row.startsWith('|')) parts.shift();
        if (row.endsWith('|')) parts.pop();
        return parts;
      });

      const headers = parsedRows[0];
      const bodyRows = parsedRows.slice(1);

      elements.push(
        <div className="table-container" style={{ margin: '12px 0' }} key={`table-${key++}`}>
          <table className="custom-table" style={{ width: '100%' }}>
            <thead>
              <tr>
                {headers.map((h, i) => (
                  <th key={`th-${i}`} style={{ padding: '8px', fontSize: '0.78rem' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((r, ri) => (
                <tr key={`tr-${ri}`}>
                  {r.map((td, tdi) => (
                    <td key={`td-${tdi}`} style={{ padding: '8px', fontSize: '0.75rem' }}>{parseInlineMarkdown(td)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      tableBuffer = [];
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Check for Table Row
      if (line.includes('|') && (line.startsWith('|') || line.endsWith('|') || line.trim().startsWith('|'))) {
        tableBuffer.push(line);
        continue;
      } else {
        // Flush accumulated table rows if we hit a non-table line
        flushTable();
      }

      // Check for Headers
      if (line.startsWith('## ')) {
        elements.push(<h2 key={key++} style={{ fontSize: '0.95rem', borderBottom: '1px solid var(--border-light)', paddingBottom: '4px', marginTop: '14px', marginBottom: '8px', fontWeight: '600', color: '#fff' }}>{parseInlineMarkdown(line.substring(3))}</h2>);
      } else if (line.startsWith('### ')) {
        elements.push(<h3 key={key++} style={{ fontSize: '0.85rem', marginTop: '12px', marginBottom: '6px', fontWeight: '600', color: '#fff' }}>{parseInlineMarkdown(line.substring(4))}</h3>);
      } else if (line.startsWith('**') && line.endsWith('**') && line.length > 4) {
        elements.push(<h3 key={key++} style={{ fontSize: '0.85rem', marginTop: '12px', marginBottom: '6px', fontWeight: '600', color: '#fff' }}>{parseInlineMarkdown(line.substring(2, line.length - 2))}</h3>);
      }
      // Check for lists
      else if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
        const content = line.trim().substring(2);
        elements.push(
          <ul key={key++} style={{ marginLeft: '16px', marginBottom: '6px' }}>
            <li style={{ fontSize: '0.82rem', color: 'var(--text-primary)' }}>{parseInlineMarkdown(content)}</li>
          </ul>
        );
      }
      else if (line.trim().match(/^\d+\.\s/)) {
        const content = line.trim().replace(/^\d+\.\s/, '');
        elements.push(
          <ol key={key++} style={{ marginLeft: '16px', marginBottom: '6px' }}>
            <li style={{ fontSize: '0.82rem', color: 'var(--text-primary)' }}>{parseInlineMarkdown(content)}</li>
          </ol>
        );
      }
      // Check for empty lines
      else if (!line.trim()) {
        elements.push(<div key={key++} style={{ height: '8px' }}></div>);
      }
      // Regular Paragraph
      else {
        elements.push(
          <p key={key++} style={{ fontSize: '0.82rem', marginBottom: '6px', lineHeight: '1.4', color: 'var(--text-primary)' }}>
            {parseInlineMarkdown(line)}
          </p>
        );
      }
    }
    
    // Flush any trailing table elements
    flushTable();

    return elements;
  };

  // Helper to parse bold (**text**), links [text](url), and code (`code`) inline styling
  const parseInlineMarkdown = (text) => {
    if (!text) return text;
    
    // Parse Links: [text](url)
    const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
    const result = [];
    let lastIndex = 0;
    
    const API_BASE = typeof window !== 'undefined' && window.location.hostname === 'localhost' ? 'http://localhost:8001' : '';
    text.replace(linkRegex, (match, linkText, linkUrl, offset) => {
      // Add plain text before
      if (offset > lastIndex) {
        result.push(text.substring(lastIndex, offset));
      }
      let targetUrl = linkUrl;
      if (targetUrl.startsWith('/') && API_BASE) {
        targetUrl = `${API_BASE}${targetUrl}`;
      }
      result.push(
        <a
          key={offset}
          href={targetUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            e.stopPropagation();
            if (typeof window !== 'undefined') window.open(targetUrl, '_blank');
          }}
          style={{ color: '#38bdf8', textDecoration: 'underline', cursor: 'pointer', fontWeight: '600', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
        >
          {linkText}
        </a>
      );
      lastIndex = offset + match.length;
      return match;
    });
    
    if (lastIndex < text.length) {
      result.push(text.substring(lastIndex));
    }
    
    const elements = [];
    result.forEach((item, idx) => {
      if (typeof item !== 'string') {
        elements.push(item);
        return;
      }
      const boldParts = item.split(/\*\*(.*?)\*\*/g);
      boldParts.forEach((part, bIdx) => {
        if (bIdx % 2 === 1) {
          elements.push(<strong key={`b-${idx}-${bIdx}`} style={{ fontWeight: '600', color: '#fff' }}>{part}</strong>);
        } else if (part) {
          elements.push(part);
        }
      });
    });

    return elements.length > 0 ? elements : text;
  };

  return (
    <div className="chat-panel panel" style={{ borderRadius: '0px 14px 14px 0px', borderLeft: 'none' }}>
      <div className="chat-header">
        <div className="chat-title-group">
          <div className="chat-avatar-pulse"></div>
          <div className="header-title-container">
            <span className="chat-title">CMS Intelligence Analyst</span>
            <span className="chat-status">
              {ollamaActive ? `Ollama Model Active` : 'Local Fallback Engine'}
            </span>
          </div>
        </div>
        {ollamaActive && (
          <span className="chat-model-tag">{ollamaModel}</span>
        )}
      </div>

      {/* Message Log */}
      <div className="chat-log">
        <div className="message-bubble assistant">
          <div className="msg-icon">
            <Bot size={18} />
          </div>
          <div className="msg-body">
            <p>Welcome to the Centralized Monitoring System operations desk. I have aggregated the live database metrics for the 17 circle Head Offices.</p>
            <p>How can I assist you with CMS incident diagnostics today?</p>
          </div>
        </div>

        {messages.map((msg, i) => (
          <div key={i} className={`message-bubble ${msg.role}`}>
            <div className="msg-icon">
              {msg.role === 'user' ? <User size={16} /> : <Bot size={18} />}
            </div>
            <div className="msg-body">
              {msg.role === 'user' ? parseInlineMarkdown(msg.content) : renderMessageContent(msg.content)}
            </div>
          </div>
        ))}

        {isTyping && (
          <div className="message-bubble assistant">
            <div className="msg-icon">
              <Bot size={18} />
            </div>
            <div className="msg-body" style={{ padding: '6px 12px' }}>
              <div className="typing-indicator">
                <div className="typing-dot"></div>
                <div className="typing-dot"></div>
                <div className="typing-dot"></div>
              </div>
            </div>
          </div>
        )}
        <div ref={logEndRef} />
      </div>

      {/* Suggested Prompts */}
      <div className="suggestions-container">
        <span className="suggestions-title">
          <Sparkles size={12} style={{ marginRight: '4px', verticalAlign: 'middle' }} />
          Centralized Queries
        </span>
        <div className="suggestions-scroll">
          {suggestions.map((sug, i) => (
            <button
              key={i}
              onClick={() => handleSuggestionClick(sug)}
              className="suggestion-chip"
            >
              {sug}
            </button>
          ))}
        </div>
      </div>

      {/* Input Form */}
      <form onSubmit={handleSubmit} className="chat-input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about active incidents, unhealthy devices, false alarms..."
          className="chat-input"
          disabled={isTyping}
        />
        <button type="submit" className="btn-send" disabled={!input.trim() || isTyping}>
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
