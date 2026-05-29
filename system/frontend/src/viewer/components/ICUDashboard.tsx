import React from 'react';
import type { BedsideMonitorData, MainConsoleData } from '@viewer/hooks/useICUData';

interface ICUDashboardProps {
  monitors: BedsideMonitorData[];
  consoleData: MainConsoleData | null;
  onBack?: () => void;
}

const StatusColor = { stable: '#22c55e', warning: '#f59e0b', critical: '#ef4444' } as const;

export const ICUDashboard: React.FC<ICUDashboardProps> = ({ monitors, consoleData, onBack }) => {
  return (
    <div style={{ padding: '20px', fontFamily: 'system-ui, sans-serif', color: '#e2e8f0', backgroundColor: '#0f172a', minHeight: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h1 style={{ margin: 0 }}>🏥 ICU Central Dashboard</h1>
        {onBack && (
          <button
            onClick={onBack}
            style={{ padding: '8px 16px', cursor: 'pointer', background: '#334155', color: 'white', border: 'none', borderRadius: '4px' }}
          >
            ← Back to 3D View
          </button>
        )}
      </div>

      {consoleData && (
        <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
          <div style={{ flex: 1, background: '#1e293b', padding: '15px', borderRadius: '8px' }}>
            <div style={{ color: '#94a3b8', fontSize: '12px' }}>OCCUPANCY</div>
            <div style={{ fontSize: '24px', fontWeight: 'bold' }}>{consoleData.totalPatients} / {consoleData.totalBeds || 8}</div>
          </div>
          <div style={{ flex: 1, background: '#1e293b', padding: '15px', borderRadius: '8px' }}>
            <div style={{ color: '#94a3b8', fontSize: '12px' }}>OCCUPANCY RATE</div>
            <div style={{ fontSize: '24px', fontWeight: 'bold', color: consoleData.occupancyRate > 80 ? '#ef4444' : '#22c55e' }}>
              {consoleData.occupancyRate}%
            </div>
          </div>
          <div style={{ flex: 1, background: '#1e293b', padding: '15px', borderRadius: '8px' }}>
            <div style={{ color: '#94a3b8', fontSize: '12px' }}>SYSTEM TIME</div>
            <div style={{ fontSize: '24px', fontWeight: 'bold' }}>{consoleData.systemTime}</div>
          </div>
        </div>
      )}

      <h2 style={{ borderBottom: '1px solid #334155', paddingBottom: '10px' }}>Bedside Monitors</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '20px' }}>
        {monitors.map((m) => (
          <div
            key={m.bedId}
            style={{
              background: '#1e293b',
              padding: '20px',
              borderRadius: '8px',
              borderLeft: `4px solid ${StatusColor[m.status]}`
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
              <span style={{ fontSize: '18px', fontWeight: 'bold' }}>{m.bedId}</span>
              <span style={{ color: StatusColor[m.status], fontWeight: 'bold' }}>{m.status.toUpperCase()}</span>
            </div>
            <div style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '10px' }}>{m.patientName}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', textAlign: 'center' }}>
              <div>
                <div style={{ fontSize: '12px', color: '#94a3b8' }}>HR</div>
                <div style={{ fontSize: '20px', fontWeight: 'bold', color: m.hr > 100 ? '#ef4444' : '#e2e8f0' }}>{m.hr}</div>
              </div>
              <div>
                <div style={{ fontSize: '12px', color: '#94a3b8' }}>SpO2</div>
                <div style={{ fontSize: '20px', fontWeight: 'bold', color: m.spo2 < 95 ? '#f59e0b' : '#e2e8f0' }}>{m.spo2}%</div>
              </div>
              <div>
                <div style={{ fontSize: '12px', color: '#94a3b8' }}>BP</div>
                <div style={{ fontSize: '20px', fontWeight: 'bold' }}>{m.bp}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ICUDashboard;