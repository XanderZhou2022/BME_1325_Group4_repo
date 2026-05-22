import { Html } from '@react-three/drei';
import type { MapLayout } from '@/parser/types';
import type { BedsideMonitorData, MainConsoleData } from '@/hooks/useICUData';

interface Props {
  layout: MapLayout;
  monitors: BedsideMonitorData[];
  consoleData: MainConsoleData | null;
  onConsoleClick?: () => void;
}

const StatusColor = { stable: '#22c55e', warning: '#f59e0b', critical: '#ef4444' } as const;

export function ICUDataOverlay({ layout, monitors, consoleData, onConsoleClick }: Props) {
  // 1. Identify the Main Console (Floating Monitor near exit at 1,2)
  // It shares the 'computer' type, so we isolate it by position first.
  const mainConsole = layout.equipment.find(e =>
    (e.tileX === 1 && e.tileY === 2) ||
    e.type === 'diagnostic_table' // Legacy fallback
  );

  // 2. Bedside Monitors: Filter for 'computer' tiles EXCLUDING the console.
  const bedsideMonitors = layout.equipment.filter(e =>
    e.type === 'computer' && e !== mainConsole
  );

  return (
    <>
      {/* 1. Bedside Monitors */}
      {bedsideMonitors.map((eq, idx) => {
        const data = monitors[idx];
        // If data is missing for a monitor position, skip rendering.
        if (!data) return null;

        // Convert tile coordinates to world coordinates
        // X = col, Z = row (since we map Y to Z in Three.js usually, or keep Y as up? 
        // Assuming standard ThreeFloorPlan mapping: tileX -> x, tileY -> z)
        // If tileY corresponds to Z axis:
        return (
          <group key={eq.equipmentId} position={[eq.tileX + 0.5, 0, eq.tileY + 0.5]}>
            <Html position={[0, 1.8, 0]} center distanceFactor={15}>
              <div style={{
                background: 'rgba(15, 23, 42, 0.9)',
                color: '#e2e8f0',
                padding: '6px 10px',
                borderRadius: '6px',
                fontSize: '11px',
                fontFamily: 'monospace',
                minWidth: '120px',
                border: `2px solid ${StatusColor[data.status]}`,
                boxShadow: `0 0 8px ${StatusColor[data.status]}40`,
                pointerEvents: 'none',
                userSelect: 'none'
              }}>
                <div style={{ fontWeight: 'bold', marginBottom: '4px', borderBottom: '1px solid #334155', paddingBottom: '2px' }}>
                  {data.bedId}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>HR</span>
                  <span style={{ color: StatusColor[data.status], fontWeight: 'bold' }}>{data.hr}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>SpO2</span>
                  <span>{data.spo2}%</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>BP</span>
                  <span>{data.bp}</span>
                </div>
              </div>
            </Html>
          </group>
        );
      })}

      {/* 2. Main Console Display */}
      {mainConsole && consoleData && (
        <group position={[mainConsole.tileX + 0.5, 0, mainConsole.tileY + 0.5]}>
          <Html position={[0, 2.2, 0]} center distanceFactor={12}>
            <div
              onClick={(e) => {
                e.stopPropagation();
                onConsoleClick?.();
              }}
              style={{
                background: 'rgba(30, 41, 59, 0.95)',
                color: 'white',
                padding: '12px 16px',
                borderRadius: '8px',
                fontSize: '13px',
                fontFamily: 'system-ui, sans-serif',
                minWidth: '280px',
                border: '1px solid #475569',
                boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
                pointerEvents: 'none',
                userSelect: 'none'
              }}>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '15px', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                🏥 <span>ICU Central Console</span>
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                <div style={{ background: '#1e293b', padding: '4px 8px', borderRadius: '4px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px' }}>Occupancy</div>
                  <div style={{ fontWeight: 'bold' }}>{consoleData.totalPatients} / 8</div>
                </div>
                <div style={{ background: '#1e293b', padding: '4px 8px', borderRadius: '4px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px' }}>Rate</div>
                  <div style={{ fontWeight: 'bold', color: consoleData.occupancyRate > 80 ? '#ef4444' : '#22c55e' }}>
                    {consoleData.occupancyRate}%
                  </div>
                </div>
              </div>
              {consoleData.activeAlerts.length > 0 && (
                <div style={{
                  marginTop: '8px',
                  background: 'rgba(239, 68, 68, 0.15)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  borderRadius: '4px',
                  padding: '6px',
                  color: '#fca5a5',
                  fontSize: '11px'
                }}>
                  <strong>⚠️ Alerts:</strong>
                  <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                    {consoleData.activeAlerts.slice(0, 2).map((alert, i) => (
                      <li key={i}>{alert}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div style={{ marginTop: '8px', textAlign: 'right', fontSize: '10px', color: '#64748b' }}>
                Last update: {consoleData.systemTime}
              </div>
            </div>
          </Html>
        </group>
      )}
    </>
  );
}