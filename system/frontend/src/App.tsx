import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import DashboardApp from './dashboard/DashboardApp';
import { MapViewer } from './viewer/MapViewer';
import ShowcasePage from './dashboard/showcase/ShowcasePage';
import ShowcaseDetailPage from './dashboard/showcase/ShowcaseDetailPage';
import AutoDemoPage from './dashboard/showcase/AutoDemoPage';

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<DashboardApp />} />
        <Route path="/viewer" element={<MapViewer />} />
        <Route path="/showcase" element={<ShowcasePage />} />
        <Route path="/showcase_detail" element={<ShowcaseDetailPage />} />
        <Route path="/auto" element={<AutoDemoPage />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </HashRouter>
  );
}