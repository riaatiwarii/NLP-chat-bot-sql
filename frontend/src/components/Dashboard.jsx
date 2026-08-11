import React, { useState } from 'react';
import { 
  Activity, AlertTriangle, ShieldAlert, WifiOff, ListFilter, 
  MapPin, UserCheck, BellRing, RefreshCw, Terminal, AlertCircle
} from 'lucide-react';

export default function Dashboard({ dashboardData, onRefresh, onCardClick }) {
  const [activeTab, setActiveTab] = useState('telemetry'); // 'telemetry' or 'incidents'

  if (!dashboardData) {
    return (
      <div className="dashboard-panel panel" style={{ borderRadius: '14px 0px 0px 14px', justifyContent: 'center', alignItems: 'center' }}>
        <RefreshCw size={22} className="header-logo" style={{ marginBottom: '12px' }} />
        <span style={{ fontSize: '0.85rem' }}>Syncing Command Center telemetry data...</span>
      </div>
    );
  }

  const { summary, active_incidents, unhealthy_devices, alerts } = dashboardData;

  // Group alerts by Use Case/Type for chart
  const getAlertGroupData = () => {
    if (!alerts) return [];
    const counts = {};
    alerts.forEach(a => {
      counts[a.alert_type] = (counts[a.alert_type] || 0) + 1;
    });
    
    return Object.entries(counts)
      .map(([name, val]) => ({ name, value: val }))
      .sort((a, b) => b.value - a.value);
  };

  const alertChartData = getAlertGroupData();
  const maxAlertCount = alertChartData.length > 0 ? Math.max(...alertChartData.map(d => d.value)) : 1;

  const handleAlertClick = (alert) => {
    onCardClick(`Tell me more about the ${alert.alert_type} alert at ${alert.branch_name}`);
  };

  const handleIncidentClick = (inc) => {
    onCardClick(`Tell me about incident ${inc.incident_id} at ${inc.branch_name}`);
  };

  return (
    <div className="dashboard-panel panel" style={{ borderRadius: '14px 0px 0px 14px', padding: '14px', gap: '14px' }}>
      
      {/* 1. Flat, Minimalist KPI Cards Row */}
      <div className="kpi-grid" style={{ gap: '10px' }}>
        <div className="kpi-card panel healthy" onClick={() => onCardClick("Show all unhealthy devices")} style={{ padding: '10px 12px' }}>
          <div className="kpi-header" style={{ fontSize: '0.7rem' }}>
            <span>System Health</span>
            <Activity size={12} />
          </div>
          <span className="kpi-value" style={{ fontSize: '1.25rem' }}>{summary.system_health_pct}%</span>
        </div>

        <div className={`kpi-card panel ${summary.active_incidents_count > 0 ? 'critical' : 'healthy'}`} onClick={() => onCardClick("How many active incidents are there today?")} style={{ padding: '10px 12px' }}>
          <div className="kpi-header" style={{ fontSize: '0.7rem' }}>
            <span>Active Tickets</span>
            <ShieldAlert size={12} />
          </div>
          <span className="kpi-value" style={{ fontSize: '1.25rem' }}>{summary.active_incidents_count}</span>
        </div>

        <div className="kpi-card panel warning" onClick={() => onCardClick("Show today's dashboard summary")} style={{ padding: '10px 12px' }}>
          <div className="kpi-header" style={{ fontSize: '0.7rem' }}>
            <span>Alerts Today</span>
            <BellRing size={12} />
          </div>
          <span className="kpi-value" style={{ fontSize: '1.25rem' }}>{summary.alerts_today_count}</span>
        </div>

        <div className="kpi-card panel info" onClick={() => onCardClick("show alerts")} style={{ padding: '10px 12px' }}>
          <div className="kpi-header" style={{ fontSize: '0.7rem' }}>
            <span>Total Alerts</span>
            <AlertCircle size={12} />
          </div>
          <span className="kpi-value" style={{ fontSize: '1.25rem' }}>{summary.total_alerts_count || 0}</span>
        </div>

        <div className={`kpi-card panel ${summary.offline_cameras > 0 ? 'critical' : 'healthy'}`} onClick={() => onCardClick("Which CCTV cameras are offline?")} style={{ padding: '10px 12px' }}>
          <div className="kpi-header" style={{ fontSize: '0.7rem' }}>
            <span>Offline CCTV</span>
            <WifiOff size={12} />
          </div>
          <span className="kpi-value" style={{ fontSize: '1.25rem' }}>{summary.offline_cameras}</span>
        </div>
      </div>

      {/* 2. Flat Tab Selector */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border-light)', paddingBottom: '2px', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: '16px' }}>
          <button 
            onClick={() => setActiveTab('telemetry')} 
            className="form-label" 
            style={{ 
              background: 'none', border: 'none', padding: '6px 0', cursor: 'pointer',
              color: activeTab === 'telemetry' ? 'var(--sbi-blue-light)' : 'var(--text-muted)',
              borderBottom: activeTab === 'telemetry' ? '2px solid var(--sbi-blue-light)' : '2px solid transparent',
              fontWeight: '600', transition: 'var(--transition-smooth)'
            }}
          >
            Live Activity & Feed
          </button>
          <button 
            onClick={() => setActiveTab('incidents')} 
            className="form-label" 
            style={{ 
              background: 'none', border: 'none', padding: '6px 0', cursor: 'pointer',
              color: activeTab === 'incidents' ? 'var(--sbi-blue-light)' : 'var(--text-muted)',
              borderBottom: activeTab === 'incidents' ? '2px solid var(--sbi-blue-light)' : '2px solid transparent',
              fontWeight: '600', transition: 'var(--transition-smooth)'
            }}
          >
            Active Incident Queue ({active_incidents ? active_incidents.length : 0})
          </button>
        </div>
        <button onClick={onRefresh} className="btn-settings" style={{ width: '26px', height: '26px', border: 'none', background: 'none' }} title="Sync Telemetry">
          <RefreshCw size={13} style={{ color: 'var(--text-secondary)' }} />
        </button>
      </div>

      {/* 3. Conditional Tab Layout */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {activeTab === 'telemetry' ? (
          <div className="charts-row" style={{ gridTemplateColumns: '1fr 1fr', height: '100%', gap: '12px' }}>
            
            {/* SVG Alert distribution */}
            <div className="chart-panel panel" style={{ background: 'transparent', border: 'none', padding: 0 }}>
              <span className="chart-title" style={{ fontSize: '0.75rem', marginBottom: '8px' }}>
                <ListFilter size={12} style={{ color: 'var(--sbi-blue-light)', marginRight: '4px' }} />
                Use Case Alert Shares (Recent Feed)
              </span>
              <div className="custom-bar-chart" style={{ gap: '10px' }}>
                {alertChartData.length === 0 ? (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>No alert logs.</span>
                ) : (
                  alertChartData.slice(0, 5).map((item, idx) => {
                    const widthPct = (item.value / maxAlertCount) * 100;
                    return (
                      <div key={idx} className="chart-bar-item" style={{ gap: '3px' }}>
                        <div className="chart-bar-info" style={{ fontSize: '0.7rem' }}>
                          <span className="chart-bar-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '75%' }}>{item.name}</span>
                          <span className="chart-bar-value">{item.value}</span>
                        </div>
                        <div className="chart-bar-container" style={{ height: '6px' }}>
                          <div 
                            className="chart-bar-fill" 
                            style={{ 
                              width: `${widthPct}%`,
                              background: `linear-gradient(90deg, var(--sbi-accent) 0%, var(--sbi-blue-light) 100%)`
                            }}
                          ></div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Scrolling Alarm Ticker */}
            <div className="ticker-panel panel" style={{ background: 'transparent', border: 'none', padding: 0 }}>
              <span className="chart-title" style={{ fontSize: '0.75rem', marginBottom: '8px' }}>
                <Terminal size={12} style={{ color: 'var(--color-critical)', marginRight: '4px' }} />
                Real-Time Alarm Feed
              </span>
              <div className="ticker-list" style={{ gap: '6px' }}>
                {alerts && alerts.length > 0 ? (
                  [...alerts].reverse().map((alt, idx) => (
                    <div 
                      key={idx} 
                      className={`ticker-item ${alt.severity.toLowerCase()}`}
                      onClick={() => handleAlertClick(alt)}
                      style={{ padding: '8px 10px', borderRadius: '6px' }}
                    >
                      <div className="ticker-content" style={{ gap: '1px' }}>
                        <div className="ticker-header">
                          <span className="ticker-type" style={{ fontSize: '0.75rem', fontWeight: '600' }}>
                            {alt.alert_type}
                          </span>
                          <span className="ticker-time" style={{ fontSize: '0.65rem' }}>
                            {alt.timestamp.split('T')[1].substring(0, 5)}
                          </span>
                        </div>
                        <span className="ticker-desc" style={{ fontSize: '0.7rem', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {alt.remarks}
                        </span>
                        <span className="ticker-branch" style={{ fontSize: '0.65rem', marginTop: '1px' }}>
                          <MapPin size={9} style={{ marginRight: '2px', verticalAlign: 'middle' }} />
                          {alt.branch_name}
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center', padding: '16px' }}>
                    Surveillance logs clear.
                  </span>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* Incident queue table */
          <div className="table-panel panel" style={{ background: 'transparent', border: 'none', padding: 0, height: '100%', overflowY: 'auto' }}>
            <div className="table-container">
              {active_incidents && active_incidents.length > 0 ? (
                <table className="custom-table">
                  <thead>
                    <tr>
                      <th style={{ padding: '8px' }}>Ticket</th>
                      <th style={{ padding: '8px' }}>Branch</th>
                      <th style={{ padding: '8px' }}>Type</th>
                      <th style={{ padding: '8px' }}>Severity</th>
                      <th style={{ padding: '8px' }}>Operator</th>
                    </tr>
                  </thead>
                  <tbody>
                    {active_incidents.map((inc) => (
                      <tr key={inc.incident_id} onClick={() => handleIncidentClick(inc)}>
                        <td style={{ fontWeight: '600', padding: '8px' }}>{inc.incident_id}</td>
                        <td style={{ padding: '8px' }}>{inc.branch_name}</td>
                        <td style={{ padding: '8px' }}>{inc.incident_type}</td>
                        <td style={{ padding: '8px' }}>
                          <span className={`tag ${inc.severity.toLowerCase()}`} style={{ fontSize: '0.65rem', padding: '2px 6px' }}>
                            {inc.severity}
                          </span>
                        </td>
                        <td style={{ padding: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.72rem' }}>
                            <UserCheck size={11} style={{ color: 'var(--text-secondary)' }} />
                            {inc.assigned_operator}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textAlign: 'center', padding: '32px' }}>
                  Central incident queue clear.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
