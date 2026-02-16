import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { WorkflowProvider } from "./components/layout/WorkflowContext";
import { Toaster } from "./components/ui/toaster";
import { GeocodingPage } from "./pages/GeocodingPage";
import { OptimizationPage } from "./pages/OptimizationPage";
import { PrintMapPage } from "./pages/PrintMapPage";
import { ResultsPage } from "./pages/ResultsPage";
import { UploadPage } from "./pages/UploadPage";
import { ValidationPage } from "./pages/ValidationPage";
import { MlPage } from "./pages/MlPage";

export function App() {
  return (
    <WorkflowProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Navigate to="/upload" replace />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/validate" element={<ValidationPage />} />
            <Route path="/geocoding" element={<GeocodingPage />} />
            <Route path="/optimization" element={<OptimizationPage />} />
            <Route path="/results" element={<ResultsPage />} />
            <Route path="/ml" element={<MlPage />} />
          </Route>
          <Route path="/print/map" element={<PrintMapPage />} />
        </Routes>
      </BrowserRouter>
      <Toaster />
    </WorkflowProvider>
  );
}
