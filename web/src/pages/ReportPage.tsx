import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { Alert, ErrorCountBadges, Loading, ResultBadge } from "../components/common";
import {
  CLASS_PLURALS,
  ERROR_CLASSES,
  formatAcpl,
  formatDate,
  PHASE_LABELS,
  PHASES,
} from "../format";
import { useAsync } from "../hooks";
import { useStatus } from "../status";
import type { UserReport } from "../types";

export function ReportPage() {
  const { user } = useParams();
  const { status } = useStatus();
  const navigate = useNavigate();

  if (!user) {
    if (!status) return <Loading />;
    const first = status.users[0];
    if (!first) {
      return (
        <section className="empty">
          <h1>Informe</h1>
          <p>Todavía no hay partidas. <Link to="/import">Importa algunas</Link> para ver tu informe.</p>
        </section>
      );
    }
    return <Navigate to={`/report/${encodeURIComponent(first)}`} replace />;
  }

  return (
    <section>
      <div className="page-header">
        <h1>Informe de {user}</h1>
        {status && status.users.length > 1 && (
          <label className="field-inline">
            Jugador
            <select value={user} onChange={(e) => navigate(`/report/${encodeURIComponent(e.target.value)}`)}>
              {status.users.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <ReportBody user={user} />
    </section>
  );
}

function ReportBody({ user }: { user: string }) {
  const report = useAsync(() => api.report(user), [user]);
  if (report.error) return <Alert kind="error">{report.error}</Alert>;
  if (!report.data) return <Loading />;
  const r = report.data;
  if (!r.known_user) return <Alert kind="warning">No hay partidas de {user}.</Alert>;
  if (r.games_analyzed === 0) {
    return (
      <Alert kind="info">
        {r.games_pending} partida(s) importada(s), ninguna analizada todavía.{" "}
        <Link to={`/?user=${encodeURIComponent(user)}`}>Analízalas desde la lista de partidas</Link>.
      </Alert>
    );
  }
  return <Report report={r} />;
}

function Report({ report }: { report: UserReport }) {
  const totalErrors = ERROR_CLASSES.reduce((sum, cls) => sum + report.counts[cls], 0);
  const maxPhase = Math.max(
    1,
    ...PHASES.map((phase) => ERROR_CLASSES.reduce((s, cls) => s + report.by_phase[phase][cls], 0)),
  );
  const played = report.results.win + report.results.loss + report.results.draw;

  return (
    <>
      {report.games_pending > 0 && (
        <Alert kind="info">
          Hay {report.games_pending} partida(s) sin analizar que no cuentan en este informe.
        </Alert>
      )}
      <div className="stats">
        <div className="stat card">
          <span className="stat-value">{report.games_analyzed}</span>
          <span className="stat-label">partidas analizadas</span>
        </div>
        <div className="stat card">
          <span className="stat-value">{formatAcpl(report.acpl)}</span>
          <span className="stat-label" title="Pérdida media por jugada en centipeones">
            ACPL (pérdida media)
          </span>
        </div>
        <div className="stat card">
          <span className="stat-value">
            {report.results.win}/{report.results.draw}/{report.results.loss}
          </span>
          <span className="stat-label">
            victorias / tablas / derrotas
            {played ? ` · ${Math.round((report.results.win / played) * 100)} % ganadas` : ""}
          </span>
        </div>
        {ERROR_CLASSES.map((cls) => (
          <div key={cls} className={`stat card stat-${cls}`}>
            <span className="stat-value">{report.counts[cls]}</span>
            <span className="stat-label">{CLASS_PLURALS[cls].toLowerCase()}</span>
          </div>
        ))}
      </div>

      <section className="card">
        <h2>Errores por fase</h2>
        {totalErrors === 0 ? (
          <p className="muted">Sin imprecisiones ni errores. ¡Enhorabuena!</p>
        ) : (
          <div className="phase-bars">
            {PHASES.map((phase) => {
              const counts = report.by_phase[phase];
              return (
                <div key={phase} className="phase-row">
                  <span className="phase-label">{PHASE_LABELS[phase]}</span>
                  <div className="phase-bar" aria-hidden="true">
                    {ERROR_CLASSES.map((cls) =>
                      counts[cls] ? (
                        <span
                          key={cls}
                          className={`phase-seg seg-${cls}`}
                          style={{ width: `${(counts[cls] / maxPhase) * 100}%` }}
                        />
                      ) : null,
                    )}
                  </div>
                  <ErrorCountBadges counts={counts} />
                </div>
              );
            })}
            <p className="legend muted small">
              {ERROR_CLASSES.map((cls) => (
                <span key={cls} className="legend-item">
                  <span className={`legend-swatch seg-${cls}`} /> {CLASS_PLURALS[cls]}
                </span>
              ))}
            </p>
          </div>
        )}
      </section>

      {report.worst_games.length > 0 && (
        <section className="card">
          <h2>Partidas con más errores</h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Rival</th>
                  <th>Resultado</th>
                  <th>Errores</th>
                  <th>ACPL</th>
                </tr>
              </thead>
              <tbody>
                {report.worst_games.map((g) => (
                  <tr key={g.id}>
                    <td>{formatDate(g.played_at)}</td>
                    <td>
                      <Link to={`/games/${g.id}`}>{g.opponent}</Link>
                    </td>
                    <td>
                      <ResultBadge result={g.user_result} />
                    </td>
                    <td>{g.summary && <ErrorCountBadges counts={g.summary.counts} />}</td>
                    <td>{formatAcpl(g.summary?.acpl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
