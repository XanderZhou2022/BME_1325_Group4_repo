import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import { DEMO_MAX_BEDS } from '@dashboard/showcase/autoDemoConstants';
import { buildFallbackQueue } from '@dashboard/showcase/autoDemoWardQueue';
import type { AdmissionBoardRow, WardPriorityQueueItem } from '@dashboard/showcase/autoDemoTypes';
import type { JsonObj } from '@dashboard/types';

export type BedStatus = 'stable' | 'warning' | 'critical' | 'empty';

export interface ViewerBedData {
  bedId: string;
  occupied: boolean;
  patientId?: string;
  admissionId?: string;
  primaryDiagnosis?: string;
  carePhase?: string;
  severity?: string;
  riskCount?: number;
  hr: number;
  spo2: number;
  bp: string;
  status: BedStatus;
}

/** @deprecated Use {@link ViewerBedData} — kept for ICUDashboard compatibility. */
export type BedsideMonitorData = ViewerBedData & { patientName: string };

export interface MainConsoleData {
  simTime: string;
  stepIndex: number;
  totalPatients: number;
  totalBeds: number;
  occupiedBeds: number;
  occupancyRate: number;
  activeAlerts: string[];
  systemTime: string;
  connectionError: string | null;
  wardQueue: WardPriorityQueueItem[];
  recentEventType: string | null;
}

interface DemoAdmission {
  admission_id: string;
  patient_id: string;
  bed_id: string;
  status: string;
  severity_on_admission?: string;
  primary_diagnosis?: string;
}

function vitalsFromState(st: JsonObj | null): { hr: number; spo2: number; bp: string } {
  const v = (st?.current_vitals ?? {}) as JsonObj;
  const hr = Number(v.heart_rate ?? 0);
  const spo2 = Number(v.spo2 ?? 0);
  const sys = v.systolic_bp;
  const dia = v.diastolic_bp;
  const bp =
    sys != null && dia != null ? `${Math.round(Number(sys))}/${Math.round(Number(dia))}` : '--/--';
  return { hr, spo2, bp };
}

function statusFromVitals(hr: number, spo2: number, bp: string, occupied: boolean): BedStatus {
  if (!occupied) return 'empty';
  const parts = bp.split('/').map((x) => parseInt(x, 10));
  const sys = parts[0];
  const dia = parts[1];
  if (
    (hr > 0 && (hr < 50 || hr > 120)) ||
    (spo2 > 0 && spo2 < 90) ||
    (Number.isFinite(sys) && sys < 80) ||
    (Number.isFinite(dia) && dia < 50)
  ) {
    return 'critical';
  }
  if (
    (hr > 0 && (hr < 60 || hr > 100)) ||
    (spo2 > 0 && spo2 < 95) ||
    (Number.isFinite(sys) && (sys < 90 || sys > 140))
  ) {
    return 'warning';
  }
  return 'stable';
}

async function enrichBoard(active: DemoAdmission[]): Promise<AdmissionBoardRow[]> {
  if (active.length === 0) return [];
  const states = await Promise.all(
    active.map((a) => api.getCurrentState(a.admission_id).catch(() => null))
  );
  return active.map((a, i) => {
    const st = states[i] as JsonObj | null;
    const risks = Array.isArray(st?.active_risks) ? (st.active_risks as unknown[]).length : 0;
    const phase = String(st?.care_phase ?? a.severity_on_admission ?? 'stable');
    return {
      admission_id: a.admission_id,
      patient_id: a.patient_id,
      bed_id: a.bed_id,
      status: a.status,
      severity_on_admission: a.severity_on_admission,
      primary_diagnosis: a.primary_diagnosis,
      admit_time: undefined,
      care_phase: phase,
      risk_count: risks,
      updated_at: String(st?.updated_at ?? '')
    };
  });
}

function boardToBedData(boardByBed: Map<string, AdmissionBoardRow>, bedId: string): ViewerBedData {
  const row = boardByBed.get(bedId);
  if (!row) {
    return {
      bedId,
      occupied: false,
      hr: 0,
      spo2: 0,
      bp: '--/--',
      status: 'empty'
    };
  }
  return {
    bedId,
    occupied: true,
    patientId: row.patient_id,
    admissionId: row.admission_id,
    primaryDiagnosis: row.primary_diagnosis,
    carePhase: row.care_phase,
    severity: row.severity_on_admission,
    riskCount: row.risk_count,
    hr: 0,
    spo2: 0,
    bp: '--/--',
    status: 'stable'
  };
}

export function useICUData(bedsCount: number = DEMO_MAX_BEDS) {
  const [bedMonitors, setBedMonitors] = useState<ViewerBedData[]>([]);
  const [mainConsole, setMainConsole] = useState<MainConsoleData | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [demoState, admissionTable] = await Promise.all([
        api.demoAutoState(),
        api.getTable('admissions', 200)
      ]);

      const st = demoState as JsonObj;
      const rows = (admissionTable.rows as unknown as DemoAdmission[]).filter(
        (r) => String((r as unknown as JsonObj).scenario_tag ?? '') === 'demo_auto'
      );
      const active = rows.filter((r) => r.status === 'active');
      const enriched = await enrichBoard(active);
      const boardByBed = new Map(enriched.map((r) => [r.bed_id, r]));

      const vitalsPairs = await Promise.all(
        enriched.map(async (row) => {
          const state = await api.getCurrentState(row.admission_id).catch(() => null);
          return [row.bed_id, vitalsFromState(state as JsonObj | null)] as const;
        })
      );
      const vitalsByBed = new Map(vitalsPairs);

      const alerts: string[] = [];
      const beds: ViewerBedData[] = [];

      for (let i = 0; i < bedsCount; i++) {
        const bedId = `demo_b_${String(i + 1).padStart(2, '0')}`;
        const base = boardToBedData(boardByBed, bedId);
        if (!base.occupied) {
          beds.push(base);
          continue;
        }
        const vitals = vitalsByBed.get(bedId) ?? { hr: 0, spo2: 0, bp: '--/--' };
        const status = statusFromVitals(vitals.hr, vitals.spo2, vitals.bp, true);
        if (status === 'critical') alerts.push(`${bedId}: 危重体征`);
        else if (status === 'warning') alerts.push(`${bedId}: 预警体征`);
        beds.push({ ...base, ...vitals, status });
      }

      let wardQueue: WardPriorityQueueItem[] = [];
      if (enriched.length > 0) {
        const wardRows = await Promise.all(
          enriched.map((r) =>
            api.getAgentOutputs(r.admission_id, 'ward_coordinator', 8).catch(() => [] as JsonObj[])
          )
        );
        for (const outputs of wardRows) {
          for (const o of outputs) {
            const payload = (o as JsonObj).payload as JsonObj | undefined;
            const q = payload?.priority_queue;
            if (Array.isArray(q) && q.length) {
              wardQueue = q as WardPriorityQueueItem[];
              break;
            }
          }
          if (wardQueue.length) break;
        }
        if (!wardQueue.length) {
          wardQueue = buildFallbackQueue(enriched).queue;
        }
      }

      const recent = Array.isArray(st.recent_events) ? (st.recent_events as JsonObj[]) : [];
      const latest = recent[0];

      setBedMonitors(beds);
      setMainConsole({
        simTime: String(st.sim_time ?? ''),
        stepIndex: Number(st.step_index ?? 0),
        totalPatients: active.length,
        totalBeds: bedsCount,
        occupiedBeds: Number(st.occupied_beds ?? active.length),
        occupancyRate: Math.min(100, Math.round((active.length / bedsCount) * 100)),
        activeAlerts: alerts,
        systemTime: new Date().toLocaleTimeString(),
        connectionError: null,
        wardQueue: wardQueue.slice(0, 5),
        recentEventType: latest ? String(latest.event_type ?? '') : null
      });
    } catch (err) {
      console.error('Failed to fetch ICU demo data:', err);
      const emptyBeds: ViewerBedData[] = Array.from({ length: bedsCount }, (_, i) => ({
        bedId: `demo_b_${String(i + 1).padStart(2, '0')}`,
        occupied: false,
        hr: 0,
        spo2: 0,
        bp: '--/--',
        status: 'empty' as const
      }));
      setBedMonitors(emptyBeds);
      setMainConsole({
        simTime: '—',
        stepIndex: 0,
        totalPatients: 0,
        totalBeds: bedsCount,
        occupiedBeds: 0,
        occupancyRate: 0,
        activeAlerts: [],
        systemTime: new Date().toLocaleTimeString(),
        connectionError: err instanceof Error ? err.message : '无法连接后端',
        wardQueue: [],
        recentEventType: null
      });
    }
  }, [bedsCount]);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const legacyMonitors: BedsideMonitorData[] = bedMonitors.map((b) => ({
    ...b,
    patientName: b.patientId ? `患者 ${b.patientId}` : '空床'
  }));

  return { bedMonitors: legacyMonitors, beds: bedMonitors, mainConsole, refresh: fetchData };
}
