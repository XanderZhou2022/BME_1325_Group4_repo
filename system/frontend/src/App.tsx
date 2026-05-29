import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AutoDemoPage from "./dashboard/showcase/AutoDemoPage";
import { MapViewer } from "./viewer/MapViewer";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MapViewer />} />
        <Route path="/viewer" element={<MapViewer />} />
        <Route path="/auto" element={<AutoDemoPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
