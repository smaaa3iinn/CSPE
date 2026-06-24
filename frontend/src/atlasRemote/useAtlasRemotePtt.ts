import { useCallback, useEffect, useRef, useState } from "react";
import { postAtlasInputMode, postChat } from "../api/client";
import { apiUrl } from "../api/config";
import {
  createRemoteSpeechSession,
  defaultSpeechLang,
  isBrowserSpeechSupported,
} from "./browserSpeech";
import { extractAssistantText } from "./extractAssistantText";

export type AtlasRemoteStatus = "idle" | "listening" | "processing" | "done" | "error";

const MIN_TRANSCRIPT_LEN = 2;
const DONE_RESET_MS = 3500;

export function useAtlasRemotePtt() {
  const [status, setStatus] = useState<AtlasRemoteStatus>("idle");
  const [liveTranscript, setLiveTranscript] = useState("");
  const [lastCommand, setLastCommand] = useState("");
  const [lastResponse, setLastResponse] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [speechSupported] = useState(() => isBrowserSpeechSupported());

  const listeningRef = useRef(false);
  const transcriptRef = useRef("");
  const speechRef = useRef<ReturnType<typeof createRemoteSpeechSession> | null>(null);
  const pendingSendRef = useRef(false);
  const sendCommandRef = useRef<(text: string) => Promise<void>>(async () => {});

  const sendCommand = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || trimmed.length < MIN_TRANSCRIPT_LEN) {
      setStatus("idle");
      setError("No speech detected — tap to listen, speak, then tap again when done.");
      transcriptRef.current = "";
      setLiveTranscript("");
      return;
    }

    setStatus("processing");
    setLastCommand(trimmed);
    setLiveTranscript("");
    setError(null);

    try {
      await postAtlasInputMode("text");
      const result = await postChat(trimmed);
      const assistant = extractAssistantText(result.structured_outputs);
      setLastResponse(assistant || "(no reply)");
      if (result.error) {
        setError(result.error);
        setStatus("error");
      } else {
        setStatus("done");
      }
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "Request failed");
    }
  }, []);

  sendCommandRef.current = sendCommand;

  const ensureSpeechSession = useCallback(() => {
    if (speechRef.current) return speechRef.current;
    speechRef.current = createRemoteSpeechSession({
      lang: defaultSpeechLang(),
      onInterim: (text) => setLiveTranscript(text),
      onAccumulated: (text) => {
        transcriptRef.current = text;
        setLiveTranscript(text);
      },
      onError: (message) => {
        if (!listeningRef.current && !pendingSendRef.current) return;
        setError(`Microphone error: ${message}`);
        setStatus("error");
        listeningRef.current = false;
        pendingSendRef.current = false;
      },
      onEnd: () => {
        if (pendingSendRef.current) {
          pendingSendRef.current = false;
          listeningRef.current = false;
          void sendCommandRef.current(transcriptRef.current);
          return;
        }
        if (listeningRef.current) {
          speechRef.current?.start();
        }
      },
    });
    return speechRef.current;
  }, []);

  const startListening = useCallback(() => {
    if (status === "processing") return;
    if (!speechSupported) {
      setStatus("error");
      setError("Speech recognition is not available in this browser. Use the text field below.");
      return;
    }

    listeningRef.current = true;
    pendingSendRef.current = false;
    transcriptRef.current = "";
    setLiveTranscript("");
    setError(null);
    setStatus("listening");
    ensureSpeechSession()?.start();
  }, [ensureSpeechSession, speechSupported, status]);

  const stopListeningAndSend = useCallback(() => {
    if (!listeningRef.current) return;
    pendingSendRef.current = true;
    speechRef.current?.stop();
  }, []);

  const toggleListening = useCallback(() => {
    if (status === "processing") return;
    if (listeningRef.current || status === "listening") {
      stopListeningAndSend();
    } else {
      startListening();
    }
  }, [startListening, status, stopListeningAndSend]);

  const sendTyped = useCallback(
    async (text: string) => {
      if (status === "processing" || status === "listening") return;
      await sendCommand(text);
    },
    [sendCommand, status],
  );

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const r = await fetch(apiUrl("/api/health"));
        if (!cancelled) setConnected(r.ok);
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    void check();
    const id = window.setInterval(() => void check(), 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (status !== "done") return;
    const id = window.setTimeout(() => setStatus("idle"), DONE_RESET_MS);
    return () => window.clearInterval(id);
  }, [status]);

  useEffect(() => {
    return () => {
      listeningRef.current = false;
      pendingSendRef.current = false;
      speechRef.current?.abort();
    };
  }, []);

  return {
    status,
    liveTranscript,
    lastCommand,
    lastResponse,
    error,
    connected,
    speechSupported,
    toggleListening,
    sendTyped,
  };
}
