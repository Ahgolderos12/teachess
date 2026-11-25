import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api";
import {
  Alert,
  ErrorCountBadges,
  JobProgress,
  Loading,
  ResultBadge,
} from "../components/common";
import { formatAcpl, formatDate, formatTimeControl, PLATFORM_LABELS } from "../format";
import { useAsync } from "../hooks";
import { useStatus } from "../status";
import type { AnalysisResult, Job } from "../types";

export function GamesPage() {
  const { status, reload: reloadStatus } = useStatus();
  const [params, setParams] = useSearchParams();
  const user = params.get("user") ?? "";
  const games = useAsync(() => api.games(user || undefined), [user]);
  const [job, setJob] = useState<Job<AnalysisResult> | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const navigate = useNavigate();

  const users = status?.users ?? [];
  const pending = (games.data ?? []).filter((g) => g.analyzed_depth === null);
  const pendingUsers = [...new Set(pending.map((g) => g.username))];
  const analysisTarget = user || (pendingUsers.length === 1 ? pendingUsers[0] : undefined);

  const analysePending = async () => {
    if (!analysisTarget) return;
    setStartError(null);
    try {
      setJob(await api.startAnalysis({ user: analysisTarget }));
    } catch (err) {
      setStartError(err instanceof Error ? err.message : String(err));
    }
  };

  if (status && status.games === 0) {
    return (
      <section className="empty">
        <h1>Bienvenido a Teachess</h1>
        <p>
          Importa tus partidas de Chess.com, Lichess o un archivo PGN. Teachess las analiza con
          Stockfish y te enseña tus errores jugada a jugada, valorados con criterio humano.
        </p>
        <button type="button" className="button button-large" onClick={() => navigate("/import")}>
          Importar partidas
        </button>
      </section>
    );
  }

  return (
    <section>
      <div className="page-header">
        <h1>Partidas</h1>
        <div className="toolbar">
          {users.length > 1 && (
            <label className="field-inline">
              Jugador
              <select
                value={user}
                onChange={(e) => setParams(e.target.value ? { user: e.target.value } : {})}
              >
                <option value="">Todos</option>
                {users.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </label>
          )}
          {status?.stockfish && pending.length > 0 && analysisTarget && !job && (
            <button type="button" className="button" onClick={analysePending}>
              Analizar pendientes ({pending.length})
            </button>
          )}
          <Link to="/import" className="button button-secondary">
            Importar
          </Link>
        </div>
      </div>

      {startError && <Alert kind="error">{startError}</Alert>}
      {job && (
        <JobProgress
          job={job}
          onFinish={() => {
            games.reload();
            reloadStatus();
          }}
          renderResult={(result) => (
            <Alert kind="success">
              Análisis terminado: {result.analyzed} partida(s) a profundidad {result.depth}.{" "}
              <button type="button" className="link-button" onClick={() => setJob(null)}>
                Cerrar
              </button>
            </Alert>
          )}
        />
      )}
      {status?.stockfish && pending.length > 0 && !analysisTarget && (
        <p className="muted small">Elige un jugador para analizar sus partidas pendientes.</p>
      )}

      {games.error && <Alert kind="error">{games.error}</Alert>}
      {games.loading && !games.data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table className="table games-table">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Rival</th>
                <th>Color</th>
                <th>Resultado</th>
                <th>Ritmo</th>
                <th>Apertura</th>
                <th title="Errores graves · errores · imprecisiones">Errores</th>
                <th title="Pérdida media en centipeones">ACPL</th>
                <th>
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(games.data ?? []).map((g) => (
                <tr key={g.id} className="clickable" onClick={() => navigate(`/games/${g.id}`)}>
                  <td>{formatDate(g.played_at)}</td>
                  <td>
                    <strong>{g.opponent}</strong>
                    <span className="muted small"> · {PLATFORM_LABELS[g.platform]}</span>
                  </td>
                  <td>
                    <span className={`color-dot color-${g.user_color}`} />{" "}
                    {g.user_color === "white" ? "Blancas" : "Negras"}
                  </td>
                  <td>
                    <ResultBadge result={g.user_result} />
                  </td>
                  <td>{formatTimeControl(g.time_control)}</td>
                  <td className="opening" title={g.opening ?? undefined}>
                    {g.opening ?? "—"}
                  </td>
                  <td>
                    {g.summary ? (
                      <ErrorCountBadges counts={g.summary.counts} />
                    ) : (
                      <span className="muted small">sin analizar</span>
                    )}
                  </td>
                  <td>{formatAcpl(g.summary?.acpl)}</td>
                  <td>
                    <Link to={`/games/${g.id}`} onClick={(e) => e.stopPropagation()}>
                      Ver
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {games.data?.length === 0 && <p className="muted">No hay partidas de este jugador.</p>}
        </div>
      )}
    </section>
  );
}
