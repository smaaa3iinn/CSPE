import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { exchangeSpotifyCode } from "../api/spotify";
import { useAppStore } from "../store";
import "./music.css";

type Phase = "idle" | "working" | "ok" | "err";

export function SpotifyCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const code = params.get("code");
    const oauthErr = params.get("error");
    const desc = params.get("error_description");

    if (oauthErr) {
      setPhase("err");
      setMessage(desc || oauthErr);
      return;
    }
    if (!code) {
      setPhase("err");
      setMessage("Missing authorization code in URL.");
      return;
    }

    setPhase("working");
    void (async () => {
      try {
        await exchangeSpotifyCode(code);
        setPhase("ok");
        window.setTimeout(() => {
          useAppStore.getState().setMode("music");
          navigate("/", { replace: true });
        }, 900);
      } catch (e) {
        setPhase("err");
        setMessage(e instanceof Error ? e.message : "Token exchange failed");
      }
    })();
  }, [params, navigate]);

  return (
    <div className="music-callback">
      <div className="music-callback__box">
        <h1>
          {phase === "working" || phase === "idle"
            ? "Connecting to Spotify…"
            : phase === "ok"
              ? "Success"
              : "Could not connect"}
        </h1>
        <p>
          {phase === "working" || phase === "idle"
            ? "Exchanging the code for tokens."
            : phase === "ok"
              ? "Opening Music…"
              : "Something went wrong."}
        </p>
        {phase === "err" && <p className="music-callback__err">{message}</p>}
      </div>
    </div>
  );
}
