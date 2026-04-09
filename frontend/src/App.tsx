import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { SpotifyCallbackPage } from "./pages/SpotifyCallbackPage";
import { useAppStore } from "./store";

/** Old /music links: switch to Music mode on the main shell. */
function MusicRouteRedirect() {
  const navigate = useNavigate();
  useEffect(() => {
    useAppStore.getState().setMode("music");
    navigate("/", { replace: true });
  }, [navigate]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />} />
        <Route path="/music" element={<MusicRouteRedirect />} />
        <Route path="/callback" element={<SpotifyCallbackPage />} />
      </Routes>
    </BrowserRouter>
  );
}
