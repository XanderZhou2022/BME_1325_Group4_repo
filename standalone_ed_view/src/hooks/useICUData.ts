import { useEffect, useState, useCallback } from 'react';

export interface BedsideMonitorData {
  bedId: string;
  patientName: string;
  hr: number;      // Heart Rate
  spo2: number;    // Blood Oxygen
  bp: string;      // Blood Pressure
  status: 'stable' | 'warning' | 'critical';
}

export interface MainConsoleData {
  totalPatients: number;
  occupancyRate: number;
  activeAlerts: string[];
  systemTime: string;
}

// 📡 Mock data generator (simulating bedside_monitor and frontend agent)
function generateMockBedData(count: number): BedsideMonitorData[] {
  const statuses: BedsideMonitorData['status'][] = ['stable', 'warning', 'critical'];
  return Array.from({ length: count }, (_, i) => ({
    bedId: `ICU-${String(i + 1).padStart(2, '0')}`,
    patientName: `Patient ${i + 1}`,
    hr: 60 + Math.floor(Math.random() * 40),
    spo2: 95 + Math.floor(Math.random() * 5),
    bp: `${110 + Math.floor(Math.random() * 20)}/${70 + Math.floor(Math.random() * 10)}`,
    status: statuses[Math.floor(Math.random() * statuses.length)]
  }));
}

export function useICUData(bedsCount: number = 6) {
  const [bedMonitors, setBedMonitors] = useState<BedsideMonitorData[]>([]);
  const [mainConsole, setMainConsole] = useState<MainConsoleData | null>(null);

  const fetchData = useCallback(() => {
    // Replace these with actual fetch calls to your Python backend later
    // Example: fetch('/api/v1/demo/auto/state')
    setBedMonitors(generateMockBedData(bedsCount));
    setMainConsole({
      totalPatients: bedsCount,
      occupancyRate: Math.floor((bedsCount / 8) * 100),
      activeAlerts: ['Bed ICU-03: SpO2 dropping', 'Ventilator sync check'],
      systemTime: new Date().toLocaleTimeString()
    });
  }, [bedsCount]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000); // Simulate real-time updates
    return () => clearInterval(interval);
  }, [fetchData]);

  return { bedMonitors, mainConsole };
}