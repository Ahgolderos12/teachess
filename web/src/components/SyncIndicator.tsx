import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import type { SyncStatus } from "../types";

const IDLE_POLL_MS = 60_000;
const RUNNING_POLL_MS = 1_500;

/** "2 h", "15 min", "unos segundos". */
function relative(seconds: number): string {
  const abs = Math.abs(seconds);
  if (abs < 60) return "unos segundos";
  if (abs < 3600) return `${Math.round(abs / 60)} min`;
  if (abs < 86_400) return `${Math.round(abs / 3600)} h`;
  return `${Math.round(abs / 86_400)} d`;
}

/** Header badge: last automatic sync with Chess.com/Lichess and a button to sync now. */
export function SyncIndicator() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newGames, setNewGames] = useState(0);

  const refresh = useCallback(() => {
    api
      .sync()
      .then((next) => {
        setStatus((previous) => {
          const finished =
            previous?.job?.status === "running" && next.job && next.job.status === "done";
          if (finished && next.job?.result?.new) setNewGames(next.job.result.new);
          return next;
        });
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const running = status?.job?.status === "running" || status?.job?.status === "queued";
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, running ? RUNNING_POLL_MS : IDLE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, running]);

  if (!status?.configured) return null;

  const syncNow = () => {
    setNewGames(0);
    api
      .syncNow()
      .then(refresh)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  };

  const job = status.job;
  const now = Date.now() / 1000;
  let label: string;
  let title = `Importa y analiza tus partidas nuevas de ${Object.values(status.users).join(", ")}`;
  if (running) {
    label = job?.message || "Sincronizando…";
  } else if (job?.status === "error") {
    label = "Error al sincronizar";
    title = job.error ?? title;
  } else if (job?.status === "done") {
    label = `Sincronizado hace ${relative(now - job.created_at)}`;
  } else {
    label = "Sin sincronizar";
  }
  if (!running && status.next_run_at && status.next_run_at > now) {
    title += ` · próxima en ${relative(status.next_run_at - now)}`;
  }

  return (
    <span className="sync">
      {newGames > 0 && (
        <button type="button" className="link-button small" onClick={() => window.location.reload()}>
          {newGames} partida(s) nueva(s): recargar
        </button>
      )}
      <span className={`pill ${job?.status === "error" || error ? "pill-warn" : "pill-muted"}`} title={error ?? title}>
        {running && <span className="spinner spinner-small" aria-hidden="true" />} {label}
      </span>
      <button
        type="button"
        className="icon-button"
        onClick={syncNow}
        disabled={running}
        aria-label="Sincronizar ahora"
        title="Sincronizar ahora"
      >
        ↻
      </button>
    </span>
  );
}
