import { Html } from '@react-three/drei';
import type { MapLayout } from '@viewer/parser/types';
import type { MainConsoleData, ViewerBedData } from '@viewer/hooks/useICUData';
import { DEMO_BED_IDS } from '@dashboard/showcase/autoDemoConstants';

interface Props {
  layout: MapLayout;
  beds: ViewerBedData[];
  consoleData: MainConsoleData | null;
  onConsoleClick?: () => void;
}

const StatusColor = {
  stable: '#22c55e',
  warning: '#f59e0b',
  critical: '#ef4444',
  empty: '#64748b'
} as const;

function phaseColor(phase: string | undefined): string {
  if (phase === 'critical') return StatusColor.critical;
  if (phase === 'unstable' || phase === 'warning') return StatusColor.warning;
  return StatusColor.stable;
}

export function ICUDataOverlay({ layout, beds, consoleData, onConsoleClick }: Props) {
  const bedById = new Map(beds.map((b) => [b.bedId, b]));
  const bedEquipById = new Map(
    layout.equipment.filter((e) => e.type === 'bed').map((e) => [e.equipmentId, e])
  );

  const mainConsoleEquip = layout.equipment.find(
    (e) =>
      (e.type === 'computer' && e.tileX === 9 && e.tileY === 9) || e.type === 'diagnostic_table'
  );

  return (
    <>
      {DEMO_BED_IDS.map((bedId) => {
        const eq = bedEquipById.get(bedId);
        const data = bedById.get(bedId);
        if (!eq || !data) return null;

        const border = StatusColor[data.status];
        const phase = data.carePhase ?? data.severity;

        return (
          <group key={bedId} position={[eq.tileX + 0.5, 0, eq.tileY + 0.5]}>
            <Html position={[0, 1.85, 0]} center distanceFactor={14}>
              <div
                style={{
                  background: 'rgba(15, 23, 42, 0.94)',
                  color: '#e2e8f0',
                  padding: '8px 10px',
                  borderRadius: '8px',
                  fontSize: '11px',
                  fontFamily: 'system-ui, sans-serif',
                  minWidth: '148px',
                  maxWidth: '200px',
                  border: `2px solid ${border}`,
                  boxShadow: `0 4px 12px ${border}55`,
                  pointerEvents: 'none',
                  userSelect: 'none'
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    marginBottom: '6px',
                    borderBottom: '1px solid #334155',
                    paddingBottom: '4px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: '8px'
                  }}
                >
                  <span>{bedId}</span>
                  <span style={{ color: border, fontSize: '10px' }}>
                    {data.occupied ? (phase ?? '—') : '空床'}
                  </span>
                </div>

                {data.occupied ? (
                  <>
                    <div style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '6px' }}>
                      {data.patientId}
                    </div>
                    <div
                      style={{
                        fontSize: '10px',
                        marginBottom: '6px',
                        color: '#cbd5e1',
                        lineHeight: 1.3
                      }}
                    >
                      {data.primaryDiagnosis ?? '—'}
                    </div>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr 1fr',
                        gap: '4px',
                        fontFamily: 'monospace',
                        fontSize: '10px',
                        marginBottom: '4px'
                      }}
                    >
                      <div>
                        <div style={{ color: '#64748b' }}>HR</div>
                        <div style={{ fontWeight: 700, color: data.hr > 100 ? '#f87171' : '#e2e8f0' }}>
                          {data.hr || '—'}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: '#64748b' }}>SpO₂</div>
                        <div style={{ fontWeight: 700, color: data.spo2 < 95 ? '#fbbf24' : '#e2e8f0' }}>
                          {data.spo2 ? `${data.spo2}%` : '—'}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: '#64748b' }}>BP</div>
                        <div style={{ fontWeight: 700 }}>{data.bp}</div>
                      </div>
                    </div>
                    <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                      风险 {data.riskCount ?? 0}
                      {data.admissionId ? ` · ${data.admissionId.slice(0, 12)}…` : ''}
                    </div>
                  </>
                ) : (
                  <div style={{ color: '#64748b', fontSize: '11px' }}>暂无患者</div>
                )}
              </div>
            </Html>
          </group>
        );
      })}

      {mainConsoleEquip && consoleData && (
        <group position={[mainConsoleEquip.tileX + 0.5, 0, mainConsoleEquip.tileY + 0.5]}>
          <Html position={[0, 2.4, 0]} center distanceFactor={11}>
            <div
              onClick={(e) => {
                e.stopPropagation();
                onConsoleClick?.();
              }}
              style={{
                background: 'rgba(30, 41, 59, 0.96)',
                color: 'white',
                padding: '12px 14px',
                borderRadius: '8px',
                fontSize: '12px',
                fontFamily: 'system-ui, sans-serif',
                minWidth: '300px',
                border: '1px solid #475569',
                boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
                cursor: 'pointer',
                pointerEvents: 'auto'
              }}
            >
              <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#38bdf8' }}>
                ICU 病区总览（与 Dashboard 同步）
              </h3>

              {consoleData.connectionError && (
                <div
                  style={{
                    background: 'rgba(239,68,68,0.15)',
                    border: '1px solid rgba(239,68,68,0.4)',
                    borderRadius: '4px',
                    padding: '6px',
                    marginBottom: '8px',
                    color: '#fca5a5',
                    fontSize: '11px'
                  }}
                >
                  后端: {consoleData.connectionError}
                  <div style={{ marginTop: '4px', color: '#94a3b8' }}>
                    请确认 8000 端口 API 已启动
                  </div>
                </div>
              )}

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '6px',
                  marginBottom: '8px'
                }}
              >
                <div style={{ background: '#1e293b', padding: '6px 8px', borderRadius: '4px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px' }}>仿真时间</div>
                  <div style={{ fontWeight: 700, fontSize: '11px' }}>
                    {String(consoleData.simTime).slice(0, 19)}
                  </div>
                </div>
                <div style={{ background: '#1e293b', padding: '6px 8px', borderRadius: '4px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px' }}>步骤</div>
                  <div style={{ fontWeight: 700 }}>#{consoleData.stepIndex}</div>
                </div>
                <div style={{ background: '#1e293b', padding: '6px 8px', borderRadius: '4px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px' }}>在院 / 床位</div>
                  <div style={{ fontWeight: 700 }}>
                    {consoleData.totalPatients} / {consoleData.totalBeds}
                  </div>
                </div>
                <div style={{ background: '#1e293b', padding: '6px 8px', borderRadius: '4px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px' }}>占用率</div>
                  <div
                    style={{
                      fontWeight: 700,
                      color: consoleData.occupancyRate > 80 ? '#f87171' : '#4ade80'
                    }}
                  >
                    {consoleData.occupancyRate}%
                  </div>
                </div>
              </div>

              {consoleData.recentEventType && (
                <div style={{ fontSize: '11px', marginBottom: '8px', color: '#cbd5e1' }}>
                  最近事件: <strong>{consoleData.recentEventType}</strong>
                </div>
              )}

              {consoleData.wardQueue.length > 0 && (
                <div style={{ marginBottom: '8px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '10px', marginBottom: '4px' }}>
                    病区优先级（Top {consoleData.wardQueue.length}）
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '11px' }}>
                    {consoleData.wardQueue.map((q, i) => (
                      <li key={`${q.admission_id}-${i}`} style={{ marginBottom: '2px' }}>
                        <span style={{ color: phaseColor(q.priority_level) }}>
                          {q.bed_id ?? '—'}
                        </span>
                        {' · '}
                        {q.patient_id ?? '—'}
                        {q.priority_level ? ` (${q.priority_level})` : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {consoleData.activeAlerts.length > 0 && (
                <div
                  style={{
                    background: 'rgba(239, 68, 68, 0.12)',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    borderRadius: '4px',
                    padding: '6px',
                    color: '#fca5a5',
                    fontSize: '11px',
                    marginBottom: '8px'
                  }}
                >
                  <strong>预警</strong>
                  <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                    {consoleData.activeAlerts.slice(0, 3).map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div style={{ textAlign: 'right', fontSize: '10px', color: '#64748b' }}>
                更新 {consoleData.systemTime} · 点击打开 Dashboard
              </div>
            </div>
          </Html>
        </group>
      )}
    </>
  );
}
