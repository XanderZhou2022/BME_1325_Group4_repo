import { useEffect, useState, useCallback } from 'react';

export interface BedsideMonitorData {
  bedId: string;
  patientName: string;
  hr: number;      // Heart Rate
  spo2: number;    // Blood Oxygen
  bp: string;      // Blood Pressure
  status: 'stable' | 'warning' | 'critical';
  admissionId?: string;
}

export interface MainConsoleData {
  totalPatients: number;
  totalBeds: number;
  occupancyRate: number;
  activeAlerts: string[];
  systemTime: string;
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface Admission {
  admission_id: string;
  bed_id: string;
  patient_id: string;
  status: string;
  primary_diagnosis?: string;
}

interface Vital {
  heart_rate?: number;
  spo2?: number;
  systolic_bp?: number;
  diastolic_bp?: number;
  mean_arterial_pressure?: number;
  respiratory_rate?: number;
  temperature?: number;
  ph?: number;
  gcs?: number;
}

function determineStatus(vital: Vital | null): 'stable' | 'warning' | 'critical' {
  if (!vital) return 'warning';
  const { heart_rate, spo2, systolic_bp, diastolic_bp } = vital;

  if (
    (heart_rate !== undefined && (heart_rate < 50 || heart_rate > 120)) ||
    (spo2 !== undefined && spo2 < 90) ||
    (systolic_bp !== undefined && systolic_bp < 80) ||
    (diastolic_bp !== undefined && diastolic_bp < 50)
  ) {
    return 'critical';
  }

  if (
    (heart_rate !== undefined && (heart_rate < 60 || heart_rate > 100)) ||
    (spo2 !== undefined && spo2 < 95) ||
    (systolic_bp !== undefined && systolic_bp < 90 || systolic_bp > 140)
  ) {
    return 'warning';
  }

  return 'stable';
}

function formatBP(vital: Vital | null): string {
  if (!vital || vital.systolic_bp == null || vital.diastolic_bp == null) {
    return '--/--';
  }
  return `${Math.round(vital.systolic_bp)}/${Math.round(vital.diastolic_bp)}`;
}

export function useICUData(bedsCount: number = 20) {
  const [bedMonitors, setBedMonitors] = useState<BedsideMonitorData[]>([]);
  const [mainConsole, setMainConsole] = useState<MainConsoleData | null>(null);

  const fetchData = useCallback(async () => {
    try {
      // Fetch admissions
      const admissionsRes = await fetch(`${API_BASE}/api/table/admissions?limit=500`);
      if (!admissionsRes.ok) throw new Error('Failed to fetch admissions');
      const admissionsData = await admissionsRes.json();
      const admissions: Admission[] = admissionsData.rows.filter((a: Admission) => a.status === 'active');

      // Fetch vitals for each active admission
      const monitors: BedsideMonitorData[] = [];
      const alerts: string[] = [];

      await Promise.all(
        admissions.map(async (admission) => {
          try {
            const vitalsRes = await fetch(`${API_BASE}/api/patient/${admission.admission_id}/vitals?limit=1`);
            let latestVital: Vital | null = null;
            if (vitalsRes.ok) {
              const vitalsData = await vitalsRes.json();
              latestVital = vitalsData[0] || null;
            }

            const status = determineStatus(latestVital);
            monitors.push({
              bedId: admission.bed_id || `BED-${admission.admission_id}`,
              patientName: `Patient ${admission.patient_id}`,
              hr: latestVital?.heart_rate ?? 0,
              spo2: latestVital?.spo2 ?? 0,
              bp: formatBP(latestVital),
              status,
              admissionId: admission.admission_id
            });

            if (status === 'critical') {
              alerts.push(`Bed ${admission.bed_id}: Critical vitals`);
            } else if (status === 'warning') {
              alerts.push(`Bed ${admission.bed_id}: Warning vitals`);
            }
          } catch {
            monitors.push({
              bedId: admission.bed_id || `BED-${admission.admission_id}`,
              patientName: `Patient ${admission.patient_id}`,
              hr: 0,
              spo2: 0,
              bp: '--/--',
              status: 'warning',
              admissionId: admission.admission_id
            });
          }
        })
      );

      // Sort monitors by bedId for consistent display
      monitors.sort((a, b) => a.bedId.localeCompare(b.bedId, undefined, { numeric: true }));

      setBedMonitors(monitors);
      setMainConsole({
        totalPatients: monitors.length,
        totalBeds: bedsCount,
        occupancyRate: Math.min(100, Math.round((monitors.length / bedsCount) * 100)),
        activeAlerts: alerts,
        systemTime: new Date().toLocaleTimeString()
      });
    } catch (err) {
      console.error('Failed to fetch ICU data:', err);
      // Fallback to empty state on error
      setBedMonitors([]);
      setMainConsole({
        totalPatients: 0,
        totalBeds: bedsCount,
        occupancyRate: 0,
        activeAlerts: ['Unable to connect to data source'],
        systemTime: new Date().toLocaleTimeString()
      });
    }
  }, [bedsCount]);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(fetchData, 5000); // Refresh every 5 seconds
    return () => clearInterval(interval);
  }, [fetchData]);

  return { bedMonitors, mainConsole };
}
