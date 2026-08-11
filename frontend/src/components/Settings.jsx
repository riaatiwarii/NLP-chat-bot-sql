import React, { useState, useEffect } from 'react';
import { X, Server, AlertCircle, CheckCircle, Shield } from 'lucide-react';

export default function Settings({ isOpen, onClose, onSave, healthData, fetchHealth, currentUseOllama }) {
  const [host, setHost] = useState('http://localhost:11434');
  const [model, setModel] = useState('llama3');
  const [useOllama, setUseOllama] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (healthData && healthData.ollama) {
      setHost(healthData.ollama.configured_host);
      setModel(healthData.ollama.configured_model);
    }
    setUseOllama(currentUseOllama);
  }, [healthData, currentUseOllama, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      // Post settings to FastAPI
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ollama_host: host,
          ollama_model: model,
        }),
      });
      if (response.ok) {
        onSave(host, model, useOllama);
        onClose();
      } else {
        alert('Failed to update backend settings');
      }
    } catch (err) {
      console.error(err);
      alert('Error updating settings: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const ollama = healthData?.ollama || { connected: false, available_models: [] };

  return (
    <div className="modal-overlay">
      <div className="modal-card panel" style={{ width: '400px', padding: '20px', gap: '14px', borderRadius: '12px' }}>
        <div className="modal-header" style={{ paddingBottom: '8px', borderBottom: '1px solid var(--border-light)' }}>
          <h3 className="modal-title" style={{ fontSize: '0.95rem' }}>
            <Server className="header-logo" size={16} />
            System Settings
          </h3>
          <button onClick={onClose} className="btn-close">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="form-group" style={{ gap: '14px' }}>
          
          {/* Main Toggle */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-light)', borderRadius: '8px' }}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '0.8rem', fontWeight: '600' }}>Ollama LLM Mode</span>
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>Use local LLM for chat response</span>
            </div>
            <input 
              type="checkbox" 
              checked={useOllama}
              onChange={(e) => setUseOllama(e.target.checked)}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
          </div>

          {/* Conditional Configurations */}
          {useOllama ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', animation: 'fade-in 0.2s ease-out' }}>
              <div className="form-group">
                <label className="form-label" style={{ fontSize: '0.65rem' }}>Ollama Host URL</label>
                <input
                  type="text"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  className="form-input"
                  style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                  placeholder="http://localhost:11434"
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" style={{ fontSize: '0.65rem' }}>Model Name</label>
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="form-input"
                  style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                  placeholder="llama3"
                  required
                />
                {ollama.available_models && ollama.available_models.length > 0 && (
                  <div style={{ marginTop: '4px' }}>
                    <span className="form-label" style={{ fontSize: '0.6rem', display: 'block', marginBottom: '4px' }}>
                      Models Pulled:
                    </span>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      {ollama.available_models.map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => setModel(m.split(':')[0])}
                          className="tag"
                          style={{
                            background: model === m.split(':')[0] ? 'var(--sbi-accent-glow)' : 'rgba(255,255,255,0.02)',
                            border: '1px solid ' + (model === m.split(':')[0] ? 'var(--sbi-blue-light)' : 'var(--border-light)'),
                            cursor: 'pointer',
                            fontSize: '0.6rem',
                            padding: '2px 6px',
                            color: model === m.split(':')[0] ? '#fff' : 'var(--text-secondary)'
                          }}
                        >
                          {m.split(':')[0]}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div
                className={`status-badge ${ollama.connected ? 'connected' : 'disconnected'}`}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px', padding: '6px 8px', fontSize: '0.68rem' }}
              >
                {ollama.connected ? (
                  <>
                    <CheckCircle size={12} />
                    Connected to Ollama (Model: {ollama.configured_model})
                  </>
                ) : (
                  <>
                    <AlertCircle size={12} />
                    Ollama Unreachable. Starts Local Fallback.
                  </>
                )}
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px', background: 'rgba(34, 197, 94, 0.04)', border: '1px solid var(--color-healthy-border)', borderRadius: '8px' }}>
              <Shield size={16} style={{ color: 'var(--color-healthy)' }} />
              <span style={{ fontSize: '0.72rem', color: 'var(--color-healthy)' }}>
                Failsafe Rule Engine Active. Answers will be generated instantly.
              </span>
            </div>
          )}

          <button type="submit" disabled={loading} className="btn-save" style={{ padding: '10px', fontSize: '0.82rem', borderRadius: '8px', marginTop: '4px' }}>
            {loading ? 'Saving Configurations...' : 'Save Settings'}
          </button>
        </form>
      </div>
    </div>
  );
}
