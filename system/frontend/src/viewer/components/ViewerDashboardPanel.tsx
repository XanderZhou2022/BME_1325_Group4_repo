import type { MainConsoleData, ViewerBedData } from '@viewer/hooks/useICUData';

interface Props {
  consoleData: MainConsoleData | null;
  beds: ViewerBedData[];
  onOpenDashboard: () => void;
}

export function ViewerDashboardPanel({ consoleData, beds, onOpenDashboard }: Props) {
  const occupied = beds.filter((b) => b.occupied);

  return (
    <section className="viewer-dash-panel" data-testid="viewer-dashboard-panel">
      <h2>病区状态</h2>
      <p className="viewer-dash-muted">与 Auto Demo Dashboard 同一数据源（10 床）</p>

      {consoleData?.connectionError && (
        <div className="viewer-dash-error" role="alert">
          {consoleData.connectionError}
        </div>
      )}

      {consoleData && (
        <dl className="viewer-dash-metrics">
          <dt>仿真时间</dt>
          <dd>{String(consoleData.simTime).slice(0, 19) || '—'}</dd>
          <dt>步骤</dt>
          <dd>#{consoleData.stepIndex}</dd>
          <dt>在院患者</dt>
          <dd>{consoleData.totalPatients}</dd>
          <dt>占用床位</dt>
          <dd>
            {consoleData.occupiedBeds} / {consoleData.totalBeds}
          </dd>
        </dl>
      )}

      <h3>床位一览</h3>
      <ul className="viewer-bed-list">
        {beds.map((b) => (
          <li
            key={b.bedId}
            className={`viewer-bed-item ${b.occupied ? 'occupied' : 'empty'} status-${b.status}`}
          >
            <span className="viewer-bed-id">{b.bedId}</span>
            {b.occupied ? (
              <>
                <span className="viewer-bed-patient">{b.patientId}</span>
                <span className="viewer-bed-vitals">
                  HR {b.hr || '—'} · SpO₂ {b.spo2 ? `${b.spo2}%` : '—'} · {b.bp}
                </span>
                <span className="viewer-bed-dx">{b.primaryDiagnosis ?? '—'}</span>
              </>
            ) : (
              <span className="viewer-bed-empty">空床</span>
            )}
          </li>
        ))}
      </ul>

      {consoleData && consoleData.wardQueue.length > 0 && (
        <>
          <h3>优先级队列</h3>
          <ol className="viewer-queue-list">
            {consoleData.wardQueue.map((q, i) => (
              <li key={`${q.admission_id}-${i}`}>
                {q.bed_id} · {q.patient_id}
                {q.priority_level ? ` · ${q.priority_level}` : ''}
              </li>
            ))}
          </ol>
        </>
      )}

      <button type="button" className="map-list-item viewer-dash-link" onClick={onOpenDashboard}>
        打开完整 Dashboard →
      </button>
    </section>
  );
}
