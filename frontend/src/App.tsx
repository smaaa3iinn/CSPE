import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AtlasRemotePage } from "./pages/AtlasRemotePage";
import { VrDevViewer } from "./viewers/VrDevViewer";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />} />
        <Route path="/atlas-remote" element={<AtlasRemotePage />} />
        <Route path="/vr-viewer" element={<VrDevViewer />} />
      </Routes>
    </BrowserRouter>
  );
}
