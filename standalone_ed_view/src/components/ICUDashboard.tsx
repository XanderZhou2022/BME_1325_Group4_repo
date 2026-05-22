import type { BedsideMonitorData, MainConsoleData } from '@/hooks/useICUData';

interface Props {
  monitors: BedsideMonitorData[];
  consoleData: MainConsoleData | null;
  onBack: () => void;
}

const StatusColor = { stable: '#22c55e', warning: '#f59e0b', critical: '#ef4444' } as const;

export function ICUDashboard({ monitors, consoleData, onBack }: Props) {
  return (
    <div style={{
      padding: '20px',
      background: '#0f172a',
      color: '#e2e8f0',
      minHeight: '100vh',
      fontFamily: 'system-ui, sans-serif'
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1 style={{ margin: 0, fontSize: '24px', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '10px' }}>
          🏥 <span>ICU Central Station</span>
        </h1>
        <button 
          onClick={onBack}
          style={{
            background: '#1e293b', border: '1px solid #475569', color: 'white',
            padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '14px'
          }}
        >
          ← Back to 3D View
        </button>
      </div>

      {/* Console Summary */}
      {consoleData && (
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '16px', marginBottom: '32px'
        }}>
          <div style={cardStyle}>
            <div style={labelStyle}>Occupancy</div>
            <div style={{ fontSize: '28px', fontWeight: 'bold' }}>{consoleData.totalPatients} / 6</div>
          </div>
          <div style={cardStyle}>
            <div style={labelStyle}>System Rate</div>
            <div style={{ fontSize: '28px', fontWeight: 'bold', color: consoleData.occupancyRate > 80 ? '#ef4444' : '#22c55e' }}>
              {consoleData.occupancyRate}%
            </div>
          </div>
          <div style={cardStyle}>
            <div style={labelStyle}>Active Alerts</div>
            <div style={{ fontSize: '28px', fontWeight: 'bold', color: '#fca5a5' }}>
              {consoleData.activeAlerts.length}
            </div>
          </div>
        </div>
      )}

      {/* Monitors Grid */}
      <h2 style={{ fontSize: '18px', color: '#94a3b8', marginBottom: '16px' }}>Bedside Monitors</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '16px' }}>
        {monitors.map((m, idx) => (
          <div key={m.bedId || idx} style={{
            ...cardStyle,
            borderLeft: `4px solid ${StatusColor[m.status] || '#64748b'}`,
            padding: '16px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px', borderBottom: '1px solid #334155', paddingBottom: '8px' }}>
              <span style={{ fontWeight: 'bold', fontSize: '16px' }}>{m.bedId}</span>
              <span style={{ color: StatusColor[m.status] || '#64748b', fontSize: '12px', textTransform: 'uppercase' }}>
                {m.status}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <VitalItem label="HR" value={m.hr} />
              <VitalItem label="SpO2" value={`${m.spo2}%`} />
              <VitalItem label="BP" value={m.bp} />
              <VitalItem label="RR" value={m.rr} />
              <VitalItem label="Temp" value={m.temp} />
              <VitalItem label="EtCO2" value={m.etco2} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function VitalItem({ label, value }: { label: string; value: string | number | undefined }) {
  return (
    <div style={{ background: '#1e293b', padding: '8px', borderRadius: '4px' }}>
      <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '16px', fontWeight: 500 }}>{value || '--'}</div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: '#1e293b',
  borderRadius: '8px',
  border: '1px solid #334155',
  padding: '12px'
};

const labelStyle: React.CSSProperties = {
  color: '#94a3b8',
  fontSize: '12px',
  marginBottom: '4px',
  textTransform: 'uppercase',
  letterSpacing: '0.05em'
};