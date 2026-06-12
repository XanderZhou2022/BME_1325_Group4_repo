import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AutoDemoPage from "./dashboard/showcase/AutoDemoPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AutoDemoPage />} />
        <Route path="/auto" element={<AutoDemoPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
