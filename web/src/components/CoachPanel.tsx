import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, askCoach } from "../api";
import { TOOL_LABELS } from "../format";
import type { Status } from "../types";
import { Alert } from "./common";

interface ChatMessage {
  role: "user" | "coach";
  text: string;
  tools: string[];
  note?: string;
  error?: string;
}

export function CoachPanel({
  gameId,
  analyzed,
  coach,
}: {
  gameId: number;
  analyzed: boolean;
  coach: Status["coach"];
}) {
  if (!coach.web_enabled) return <FreeCoachHint gameId={gameId} command={coach.mcp_command} />;
  if (!analyzed) {
    return (
      <section className="card coach">
        <h2>Coach</h2>
        <p className="muted">Analiza la partida para poder hablar de ella con el coach.</p>
      </section>
    );
  }
  return <CoachChat gameId={gameId} model={coach.model} />;
}

function FreeCoachHint({ gameId, command }: { gameId: number; command: string }) {
  const [copied, setCopied] = useState(false);
  const full = `${command} ${gameId}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <section className="card coach">
      <h2>Coach</h2>
      <p>
        Habla de esta partida con el coach <strong>gratis desde Claude Code</strong>, con tu
        suscripción: abre Claude Code en la carpeta de Teachess y escribe:
      </p>
      <div className="command">
        <code>{full}</code>
        <button type="button" className="button button-small" onClick={copy}>
          {copied ? "¡Copiado!" : "Copiar"}
        </button>
      </div>
      <p className="muted small">
        El chat aquí en la web usa la API de pago de Anthropic y solo se activa si pones
        <code> ANTHROPIC_API_KEY</code> en el archivo <code>.env</code>.
      </p>
    </section>
  );
}

function CoachChat({ gameId, model }: { gameId: number; model: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    sessionRef.current = null;
    setMessages([]);
    setError(null);
  }, [gameId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);

  const updateLast = (change: (message: ChatMessage) => ChatMessage) =>
    setMessages((all) => [...all.slice(0, -1), change(all[all.length - 1]!)]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    setMessages((all) => [
      ...all,
      { role: "user", text, tools: [] },
      { role: "coach", text: "", tools: [] },
    ]);
    try {
      if (!sessionRef.current) {
        sessionRef.current = (await api.createCoachSession(gameId)).session_id;
      }
      await askCoach(sessionRef.current, text, (ev) => {
        if (ev.type === "text") updateLast((m) => ({ ...m, text: m.text + ev.text }));
        else if (ev.type === "tool") updateLast((m) => ({ ...m, tools: [...m.tools, ev.name] }));
        else if (ev.type === "error") updateLast((m) => ({ ...m, error: ev.message }));
        else if (ev.type === "done") {
          const note = ev.refused
            ? "El modelo no ha respondido a esta pregunta. Prueba a reformularla."
            : ev.truncated
              ? "Respuesta cortada por longitud; pide que continúe."
              : undefined;
          updateLast((m) => ({ ...m, note }));
        }
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("caducado")) sessionRef.current = null;
      setMessages((all) => all.slice(0, -1));
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card coach">
      <h2>Coach</h2>
      <p className="muted small">
        Usa la API de pago de Anthropic ({model}). Las jugadas y evaluaciones salen de Stockfish.
      </p>
      <div className="chat" aria-live="polite">
        {messages.length === 0 && (
          <p className="muted">Pregunta, por ejemplo: «¿Cuál fue mi peor error y por qué?»</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-message chat-${m.role}`}>
            {m.tools.length > 0 && (
              <div className="chat-tools">
                {m.tools.map((tool, j) => (
                  <span key={j} className="chip">
                    consultando {TOOL_LABELS[tool] ?? tool}
                  </span>
                ))}
              </div>
            )}
            {m.text ? (
              <p className="chat-text">{m.text}</p>
            ) : (
              m.role === "coach" && !m.error && busy && i === messages.length - 1 && (
                <p className="muted">Pensando…</p>
              )
            )}
            {m.note && <p className="muted small">{m.note}</p>}
            {m.error && <Alert kind="error">{m.error}</Alert>}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      <form className="chat-form" onSubmit={send}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Escribe tu pregunta…"
          rows={2}
          maxLength={2000}
          disabled={busy}
          aria-label="Pregunta para el coach"
        />
        <button type="submit" className="button" disabled={busy || !input.trim()}>
          {busy ? "…" : "Enviar"}
        </button>
      </form>
    </section>
  );
}
