type SpeechCtor = new () => SpeechRecognition;

function speechCtor(): SpeechCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isBrowserSpeechSupported(): boolean {
  return speechCtor() !== null;
}

export function defaultSpeechLang(): string {
  const nav = (typeof navigator !== "undefined" ? navigator.language : "en-US") || "en-US";
  return nav.toLowerCase().startsWith("fr") ? "fr-FR" : "en-US";
}

export type RemoteSpeechSession = {
  start: () => void;
  stop: () => void;
  abort: () => void;
};

export function createRemoteSpeechSession(opts: {
  lang: string;
  onInterim: (text: string) => void;
  onAccumulated: (text: string) => void;
  onError: (message: string) => void;
  onEnd: () => void;
}): RemoteSpeechSession | null {
  const Ctor = speechCtor();
  if (!Ctor) return null;

  const rec = new Ctor();
  rec.lang = opts.lang;
  rec.continuous = true;
  rec.interimResults = true;
  rec.maxAlternatives = 1;

  const finals: string[] = [];

  rec.onresult = (ev: SpeechRecognitionEvent) => {
    let interim = "";
    for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
      const result = ev.results[i];
      const chunk = (result[0]?.transcript ?? "").trim();
      if (!chunk) continue;
      if (result.isFinal) finals.push(chunk);
      else interim = [interim, chunk].filter(Boolean).join(" ").trim();
    }
    if (interim) opts.onInterim(interim);
    const joined = finals.join(" ").replace(/\s+/g, " ").trim();
    if (joined) opts.onAccumulated(joined);
  };

  rec.onerror = (ev: SpeechRecognitionErrorEvent) => {
    const code = (ev.error || "unknown").trim();
    if (code === "aborted" || code === "no-speech") return;
    opts.onError(code);
  };

  rec.onend = () => opts.onEnd();

  const safe = (fn: () => void) => {
    try {
      fn();
    } catch {
      /* already started / stopped */
    }
  };

  return {
    start: () => {
      finals.length = 0;
      safe(() => rec.start());
    },
    stop: () => safe(() => rec.stop()),
    abort: () => safe(() => rec.abort()),
  };
}
