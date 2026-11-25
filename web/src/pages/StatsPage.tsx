import { useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { BarList, LineChart, ResultBar, ResultLegend, StatTile } from "../components/charts";
import { Alert, ErrorCountBadges, Loading, ResultBadge } from "../components/common";
import { CompareView } from "../components/CompareView";
import { FilterBar } from "../components/FilterBar";
import {
  COMPARE_PRESETS,
  describeFilter,
  filterQuery,
  isEmptyFilter,
  patchFilter,
  readFilter,
  type StatsFilter,
  writeFilter,
} from "../filters";
import {
  CLASS_PLURALS,
  COLOR_LABELS,
  ERROR_CLASSES,
  formatDate,
  formatNumber,
  formatTimeControl,
  movingAverage,
  PHASE_LABELS,
  PHASES,
  TERMINATION_LABELS,
  TIME_CLASS_LABELS,
} from "../format";
import { useAsync } from "../hooks";
import { useStatus } from "../status";
import type { Diagnosis, Outcome, PlayerStats } from "../types";

/** Called by a chart row to filter the page by it (clicking the active row clears it). */
type OnFilter = (patch: Partial<StatsFilter>) => void;

interface SectionProps {
  stats: PlayerStats;
  filter: StatsFilter;
  onFilter: OnFilter;
}

const OUTCOME_HEADINGS: Record<Outcome, string> = {
  win: "Victorias",
  draw: "Tablas",
  loss: "Derrotas",
};

export function StatsPage() {
  const { user } = useParams();
  const { status } = useStatus();
  const navigate = useNavigate();

  if (!user) {
    if (!status) return <Loading />;
    const first = status.users[0];
    if (!first) {
      return (
        <section className="empty">
          <h1>Estadísticas</h1>
          <p>
            Todavía no hay partidas. <Link to="/import">Importa algunas</Link> para ver tus
            estadísticas.
          </p>
        </section>
      );
    }
    return <Navigate to={`/stats/${encodeURIComponent(first)}`} replace />;
  }

  return (
    <section>
      <div className="page-header">
        <h1>Estadísticas de {user}</h1>
        {status && status.users.length > 1 && (
          <label className="field-inline">
            Jugador
            <select
              value={user}
              onChange={(e) =>
                navigate(`/stats/${encodeURIComponent(e.target.value)}${window.location.search}`)
              }
            >
              {status.users.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <StatsBody user={user} />
    </section>
  );
}

function groupLabel(filter: StatsFilter): string {
  const chips = describeFilter(filter);
  return chips.length ? chips.map((c) => c.label).join(", ") : "todas las partidas";
}

function StatsBody({ user }: { user: string }) {
  const [params, setParams] = useSearchParams();
  const filter = readFilter(params);
  const filterB = readFilter(params, "b_");
  const comparing = params.get("compare") === "1";
  const query = filterQuery(filter);
  const queryB = filterQuery(filterB);
  const stats = useAsync(() => api.stats(user, query), [user, query]);
  const statsB = useAsync(
    () => (comparing ? api.stats(user, queryB) : Promise.resolve(null)),
    [user, queryB, comparing],
  );
  const diagnosis = useAsync(() => api.diagnosis(user), [user]);

  const setFilter = (next: StatsFilter, prefix = "") =>
    setParams(writeFilter(params, next, prefix), { replace: false });
  const onFilter: OnFilter = (patch) => setFilter(patchFilter(filter, patch));
  const setCompare = (on: boolean, a?: StatsFilter, b?: StatsFilter) => {
    let next = new URLSearchParams(params);
    if (on) {
      next.set("compare", "1");
      if (a) next = writeFilter(next, a);
      if (b) next = writeFilter(next, b, "b_");
    } else {
      next.delete("compare");
      next = writeFilter(next, {}, "b_");
    }
    setParams(next);
  };

  if (stats.error) return <Alert kind="error">{stats.error}</Alert>;
  if (!stats.data) return <Loading />;
  const s = stats.data;
  const options = s.options;
  const empty = s.summary.record.games === 0;

  return (
    <>
      {diagnosis.data && isEmptyFilter(filter) && !comparing && (
        <TeacherView diagnosis={diagnosis.data} />
      )}
      <div className="compare-toolbar">
        <button
          type="button"
          className={`button button-small ${comparing ? "" : "button-secondary"}`}
          onClick={() => setCompare(!comparing)}
          aria-pressed={comparing}
        >
          {comparing ? "Dejar de comparar" : "Comparar dos grupos"}
        </button>
        <span className="muted small">Comparaciones rápidas:</span>
        {COMPARE_PRESETS.map(([label, a, b]) => (
          <button key={label} type="button" className="chip" onClick={() => setCompare(true, a, b)}>
            {label}
          </button>
        ))}
        {stats.loading && <span className="spinner spinner-small" aria-label="Actualizando" />}
      </div>
      <div className={comparing ? "grid-2" : ""}>
        <FilterBar
          filter={filter}
          options={options}
          onChange={(next) => setFilter(next)}
          title={comparing ? "Grupo A" : undefined}
          matching={s.summary.record.games}
        />
        {comparing && (
          <FilterBar
            filter={filterB}
            options={options}
            onChange={(next) => setFilter(next, "b_")}
            title="Grupo B"
            matching={statsB.data?.summary.record.games}
          />
        )}
      </div>
      {comparing && statsB.data && (
        <CompareView a={s} b={statsB.data} labelA={groupLabel(filter)} labelB={groupLabel(filterB)} />
      )}
      {comparing && statsB.error && <Alert kind="error">{statsB.error}</Alert>}
      {comparing && <h2 className="section-title">Detalle del grupo A</h2>}
      {empty ? (
        <Alert kind="info">Ninguna partida cumple estos filtros.</Alert>
      ) : (
        <>
          {s.games_pending > 0 && (
            <Alert kind="info">
              {s.games_pending} partida(s) sin analizar: cuentan en resultados y aperturas, pero
              no en errores, tiempo ni conversión.
            </Alert>
          )}
          <Summary stats={s} />
          <Evolution stats={s} />
          <Results stats={s} filter={filter} onFilter={onFilter} />
          <Errors stats={s} />
          <Time stats={s} />
          <Openings stats={s} filter={filter} onFilter={onFilter} />
          <Monthly stats={s} filter={filter} onFilter={onFilter} />
          <GamesList stats={s} />
          <WorstGames stats={s} />
        </>
      )}
    </>
  );
}

function TeacherView({ diagnosis }: { diagnosis: Diagnosis }) {
  if (!diagnosis.findings.length) return null;
  return (
    <section className="card teacher-view">
      <div className="card-header">
        <h2>Lo que ve tu profesor</h2>
        <Link to="/teacher" className="button button-small">
          Empezar clase
        </Link>
      </div>
      <p className="muted small">
        Patrones en tus últimas {diagnosis.window.games} partidas analizadas, ordenados por los
        puntos que te han costado.
      </p>
      <ol className="findings">
        {diagnosis.findings.map((f) => (
          <li key={f.kind}>
            <strong>{f.title}.</strong> {f.summary}{" "}
            <span className="muted small">
              {f.points_lost ? `(${formatNumber(f.points_lost)} puntos perdidos)` : ""}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Summary({ stats }: { stats: PlayerStats }) {
  const { summary } = stats;
  const r = summary.record;
  const streak = summary.streaks.current;
  return (
    <div className="stats">
      <StatTile value={String(r.games)} label="partidas" />
      <StatTile
        value={`${r.score_pct ?? "—"} %`}
        label={`de puntos · ${r.wins} V, ${r.draws} T, ${r.losses} D`}
      />
      <StatTile
        value={formatNumber(summary.accuracy)}
        label="precisión media"
        hint="Media de la precisión por jugada (fórmula de Lichess) en las partidas analizadas"
      />
      <StatTile
        value={formatNumber(summary.acpl, 0)}
        label="ACPL (pérdida media)"
        hint="Pérdida media por jugada en centipeones"
      />
      {summary.ratings.slice(0, 2).map((rating) => (
        <StatTile
          key={rating.time_class}
          value={String(rating.latest)}
          label={`ELO ${(TIME_CLASS_LABELS[rating.time_class] ?? rating.time_class).toLowerCase()} · ${rating.change >= 0 ? "+" : ""}${rating.change} · máx. ${rating.peak}`}
          tone={rating.change > 0 ? "good" : rating.change < 0 ? "bad" : undefined}
        />
      ))}
      {streak && (
        <StatTile
          value={String(streak.games)}
          label={`${streak.outcome === "win" ? "victorias" : streak.outcome === "loss" ? "derrotas" : "tablas"} seguidas (racha actual) · récord ${summary.streaks.longest_win} V`}
        />
      )}
    </div>
  );
}

function Evolution({ stats }: { stats: PlayerStats }) {
  const classes = stats.summary.ratings.map((r) => r.time_class);
  const [timeClass, setTimeClass] = useState(classes[0]);
  const rated = stats.timeline.filter((p) => p.time_class === timeClass && p.rating !== null);
  const analysed = stats.timeline.filter((p) => p.accuracy !== null);
  const accuracy = analysed.map((p) => p.accuracy);
  return (
    <div className="grid-2">
      <section className="card">
        <div className="card-header">
          <h2>Evolución del ELO</h2>
          {classes.length > 1 && (
            <div className="tabs" role="tablist">
              {classes.map((tc) => (
                <button
                  key={tc}
                  type="button"
                  role="tab"
                  aria-selected={tc === timeClass}
                  className={`tab ${tc === timeClass ? "tab-active" : ""}`}
                  onClick={() => setTimeClass(tc)}
                >
                  {TIME_CLASS_LABELS[tc] ?? tc}
                </button>
              ))}
            </div>
          )}
        </div>
        <LineChart
          ariaLabel="ELO por partida"
          format={(v) => formatNumber(v, 0)}
          points={rated.map((p) => ({
            label: formatDate(p.played_at),
            value: p.rating,
            detail: formatTimeControl(p.time_control),
          }))}
        />
      </section>
      <section className="card">
        <h2>Precisión por partida</h2>
        <LineChart
          ariaLabel="Precisión por partida, con media móvil de 10 partidas"
          points={analysed.map((p) => ({
            label: formatDate(p.played_at),
            value: p.accuracy,
            detail: `${p.blunders ?? 0} errores graves`,
          }))}
          smooth={movingAverage(accuracy, 10)}
        />
        <p className="muted small">Línea fina: cada partida. Línea gruesa: media de las 10 últimas.</p>
      </section>
    </div>
  );
}

/** Toggle: clicking the active value clears it. */
function toggle<K extends keyof StatsFilter>(filter: StatsFilter, key: K, value: StatsFilter[K]) {
  return { [key]: filter[key] === value ? undefined : value } as Partial<StatsFilter>;
}

function Results({ stats, filter, onFilter }: SectionProps) {
  const { results, terminations, duration, conversion } = stats;
  return (
    <>
      <div className="grid-2">
        <section className="card">
          <h2>Resultados</h2>
          <h3>Por color</h3>
          {(["white", "black"] as const).map((color) => (
            <ResultBar
              key={color}
              label={COLOR_LABELS[color]}
              record={results.by_color[color]}
              active={filter.color === color}
              onSelect={() => onFilter(toggle(filter, "color", color))}
            />
          ))}
          <h3>Por ritmo</h3>
          {results.by_time_class.map((row) => (
            <ResultBar
              key={row.key}
              label={TIME_CLASS_LABELS[row.key] ?? row.key}
              record={row}
              active={filter.time_class === row.key}
              onSelect={() => onFilter(toggle(filter, "time_class", row.key))}
            />
          ))}
          <h3>Por control de tiempo</h3>
          {results.by_time_control.map((row) => (
            <ResultBar
              key={row.key}
              label={formatTimeControl(row.key)}
              record={row}
              active={filter.time_control === row.key}
              onSelect={() => onFilter(toggle(filter, "time_control", row.key))}
            />
          ))}
          <ResultLegend />
        </section>
        <section className="card">
          <h2>Cuándo y contra quién</h2>
          <h3>Según el ELO del rival (antes de la partida)</h3>
          {results.by_rating_diff.map((row) => {
            const min = row.min_gap ?? undefined;
            const max = row.max_gap ?? undefined;
            const active = filter.min_gap === min && filter.max_gap === max && !isEmptyFilter({ min_gap: min, max_gap: max });
            return (
              <ResultBar
                key={row.key}
                label={row.key}
                record={row}
                active={active}
                onSelect={() =>
                  onFilter(active ? { min_gap: undefined, max_gap: undefined } : { min_gap: min, max_gap: max })
                }
              />
            );
          })}
          <p className="muted small">
            ELO de ambos antes de la partida (Chess.com guarda el de después; se estima).
          </p>
          <h3>Por momento del día</h3>
          {results.by_time_of_day.map((row) => (
            <ResultBar
              key={row.key}
              label={row.key}
              record={row}
              active={filter.day_block === row.value}
              onSelect={() => onFilter(toggle(filter, "day_block", row.value))}
            />
          ))}
          <h3>Por día de la semana</h3>
          {results.by_weekday.map((row) => (
            <ResultBar
              key={row.key}
              label={row.key}
              record={row}
              active={filter.weekday === row.value}
              onSelect={() => onFilter(toggle(filter, "weekday", row.value))}
            />
          ))}
        </section>
      </div>
      <div className="grid-2">
        <section className="card">
          <h2>Cómo terminan tus partidas</h2>
          {(["win", "loss", "draw"] as const).map((outcome) => {
            const rows = Object.entries(terminations[outcome]);
            if (!rows.length) return null;
            return (
              <div key={outcome}>
                <h3>
                  {OUTCOME_HEADINGS[outcome]}
                  <span className="muted small">
                    {" "}
                    · {formatNumber(duration[outcome], 0)} jugadas de media
                  </span>
                </h3>
                <BarList
                  className={`seg-${outcome}`}
                  format={(v) => formatNumber(v, 0)}
                  rows={rows.map(([key, value]) => ({
                    key: TERMINATION_LABELS[key] ?? key,
                    value,
                    active: filter.termination === key && filter.outcome === outcome,
                    onSelect: () =>
                      onFilter(
                        filter.termination === key && filter.outcome === outcome
                          ? { termination: undefined, outcome: undefined }
                          : { termination: key, outcome },
                      ),
                  }))}
                />
              </div>
            );
          })}
        </section>
        <section className="card">
          <h2>Ventajas y desventajas</h2>
          <div className="stats stats-inline">
            <StatTile
              value={`${formatNumber(conversion.conversion_pct, 0)} %`}
              label={`de partidas ganadoras convertidas (${conversion.converted} de ${conversion.winning_games})`}
              hint="Partidas en las que llegaste a ≥ 80 % de probabilidad de ganar durante dos jugadas seguidas"
            />
            <StatTile
              value={`${formatNumber(conversion.save_pct, 0)} %`}
              label={`de partidas perdidas salvadas (${conversion.saved} de ${conversion.losing_games})`}
              hint="Partidas en las que caíste a ≤ 20 % de probabilidad de ganar y no perdiste"
            />
          </div>
          <h3>¿Cuándo se decide la partida?</h3>
          <p className="muted small">
            Jugada del error decisivo (tras él ya no se recupera) en {stats.decisive_errors.with_decisive_error}{" "}
            de las {stats.decisive_errors.not_won} partidas no ganadas; de media en la jugada{" "}
            {formatNumber(stats.decisive_errors.avg_move_number, 0)}, pensando{" "}
            {formatNumber(stats.decisive_errors.avg_seconds_spent)} s.
          </p>
          <BarList
            className="seg-loss"
            format={(v) => formatNumber(v, 0)}
            rows={stats.decisive_errors.by_move_number.map((row) => ({
              key: `jugadas ${row.key}`,
              value: row.games,
            }))}
          />
        </section>
      </div>
    </>
  );
}

function Errors({ stats }: { stats: PlayerStats }) {
  const { errors } = stats;
  if (!errors.moves) return null;
  return (
    <section className="card">
      <h2>Errores</h2>
      <div className="stats stats-inline">
        {ERROR_CLASSES.map((cls) => (
          <div key={cls} className={`stat card stat-${cls}`}>
            <span className="stat-value">{errors.counts[cls]}</span>
            <span className="stat-label">
              {CLASS_PLURALS[cls].toLowerCase()} · {formatNumber(errors.per_game[cls], 2)} por
              partida
            </span>
          </div>
        ))}
        <StatTile
          value={String(errors.games_without_serious_errors)}
          label="partidas sin errores ni errores graves"
        />
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Fase</th>
              <th>Jugadas</th>
              <th title="Errores y errores graves cada 100 jugadas">Errores serios / 100</th>
              <th title="Caída media de probabilidad de victoria por jugada">Pérdida media</th>
              <th>Errores</th>
            </tr>
          </thead>
          <tbody>
            {PHASES.map((phase) => {
              const row = errors.by_phase[phase];
              return (
                <tr key={phase}>
                  <td>{PHASE_LABELS[phase]}</td>
                  <td>{row.moves}</td>
                  <td>{formatNumber(row.serious_per_100)}</td>
                  <td>{row.avg_win_loss_pct === null ? "—" : `${formatNumber(row.avg_win_loss_pct)} %`}</td>
                  <td>{row.counts && <ErrorCountBadges counts={row.counts} />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Time({ stats }: { stats: PlayerStats }) {
  const { time } = stats;
  if (!time.think_time.some((b) => b.moves)) return null;
  return (
    <section className="card">
      <h2>Gestión del tiempo</h2>
      <div className="stats stats-inline">
        {PHASES.map((phase) => (
          <StatTile
            key={phase}
            value={`${formatNumber(time.avg_seconds_by_phase[phase])} s`}
            label={`por jugada en ${PHASE_LABELS[phase].toLowerCase()}`}
          />
        ))}
        <StatTile
          value={`${formatNumber(time.low_clock_moves_pct)} %`}
          label="de jugadas con menos del 10 % del tiempo"
        />
        <StatTile
          value={String(time.losses_on_time)}
          label={`derrotas por tiempo (${time.wins_on_time} victorias)`}
        />
        <StatTile
          value={`${formatNumber(time.avg_clock_left_pct_end_of_losses, 0)} %`}
          label="del tiempo te queda de media al perder"
        />
      </div>
      <div className="grid-2">
        <div>
          <h3>Errores serios según lo que piensas cada jugada</h3>
          <BarList
            className="seg-mistake"
            format={(v) => `${formatNumber(v)} %`}
            rows={time.think_time.map((b) => ({
              key: b.key,
              value: b.serious_pct,
              note: `${b.moves} jugadas`,
            }))}
          />
        </div>
        <div>
          <h3>Errores serios cada 100 jugadas según el reloj</h3>
          <BarList
            className="seg-mistake"
            rows={[
              { key: "menos del 10 %", value: time.serious_per_100_low_clock },
              { key: "resto", value: time.serious_per_100_otherwise },
            ]}
          />
        </div>
      </div>
    </section>
  );
}

function Openings({ stats, filter, onFilter }: SectionProps) {
  if (!stats.openings.length) return null;
  return (
    <section className="card">
      <h2>Aperturas</h2>
      <p className="muted small">Pulsa una apertura para ver todas tus estadísticas con ella.</p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Apertura</th>
              <th>Color</th>
              <th>Resultados</th>
              <th>Precisión</th>
              <th title="Partidas perdidas o empatadas por un error antes de la jugada 16">
                Decididas pronto
              </th>
            </tr>
          </thead>
          <tbody>
            {stats.openings.map((o) => (
              <tr key={`${o.opening}-${o.color}`}>
                <td>
                  <button
                    type="button"
                    className={`link-button ${filter.opening === o.opening && filter.color === o.color ? "selected-text" : ""}`}
                    title="Filtrar por esta apertura y color"
                    onClick={() =>
                      onFilter(
                        filter.opening === o.opening && filter.color === o.color
                          ? { opening: undefined, color: undefined }
                          : { opening: o.opening, color: o.color },
                      )
                    }
                  >
                    {o.opening}
                  </button>{" "}
                  <Link to={`/games/${o.last_game_id}`} className="muted small" title="Última partida con esta apertura">
                    última ↗
                  </Link>
                </td>
                <td>{COLOR_LABELS[o.color]}</td>
                <td className="cell-bar">
                  <ResultBar label="" record={o} />
                </td>
                <td>{formatNumber(o.accuracy)}</td>
                <td>{o.decided_early || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ResultLegend />
    </section>
  );
}

function monthEnd(month: string): string {
  const [year, m] = month.split("-").map(Number);
  const last = new Date(year!, m!, 0).getDate();
  return `${month}-${String(last).padStart(2, "0")}`;
}

function Monthly({ stats, filter, onFilter }: SectionProps) {
  if (stats.monthly.length < 2) return null;
  return (
    <section className="card">
      <h2>Mes a mes</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Mes</th>
              <th>Resultados</th>
              <th>Precisión</th>
              <th>ACPL</th>
            </tr>
          </thead>
          <tbody>
            {[...stats.monthly].reverse().map((m) => (
              <tr
                key={m.month}
                className={`clickable ${filter.since === `${m.month}-01` && filter.until === monthEnd(m.month) ? "row-selected" : ""}`}
                title="Filtrar por este mes"
                onClick={() =>
                  onFilter(
                    filter.since === `${m.month}-01` && filter.until === monthEnd(m.month)
                      ? { since: undefined, until: undefined }
                      : { since: `${m.month}-01`, until: monthEnd(m.month) },
                  )
                }
              >
                <td>{new Date(`${m.month}-01T00:00:00`).toLocaleDateString("es-ES", { month: "long", year: "numeric" })}</td>
                <td className="cell-bar">
                  <ResultBar label="" record={m} />
                </td>
                <td>{formatNumber(m.accuracy)}</td>
                <td>{formatNumber(m.acpl, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const GAMES_PAGE = 25;

function GamesList({ stats }: { stats: PlayerStats }) {
  const [all, setAll] = useState(false);
  const games = [...stats.timeline].reverse();
  const shown = all ? games : games.slice(0, GAMES_PAGE);
  return (
    <section className="card">
      <div className="card-header">
        <h2>Partidas ({games.length})</h2>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Rival</th>
              <th>Color</th>
              <th>Apertura</th>
              <th>Ritmo</th>
              <th>Resultado</th>
              <th title="ELO del rival menos el tuyo, antes de la partida">Δ ELO</th>
              <th>Precisión</th>
              <th title="Errores graves">??</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((g) => (
              <tr key={g.game_id}>
                <td>{formatDate(g.played_at)}</td>
                <td>
                  <Link to={`/games/${g.game_id}`}>{g.opponent}</Link>
                </td>
                <td>{COLOR_LABELS[g.user_color]}</td>
                <td className="opening">{g.opening ?? "—"}</td>
                <td>{formatTimeControl(g.time_control)}</td>
                <td>
                  <ResultBadge result={g.outcome} />{" "}
                  <span className="muted small">{TERMINATION_LABELS[g.termination] ?? ""}</span>
                </td>
                <td>{g.rating_gap === null ? "—" : `${g.rating_gap > 0 ? "+" : ""}${g.rating_gap}`}</td>
                <td>{formatNumber(g.accuracy)}</td>
                <td>{g.blunders ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {games.length > GAMES_PAGE && (
        <button type="button" className="link-button" onClick={() => setAll(!all)}>
          {all ? "Ver menos" : `Ver las ${games.length}`}
        </button>
      )}
    </section>
  );
}

function WorstGames({ stats }: { stats: PlayerStats }) {
  if (!stats.worst_games.length) return null;
  return (
    <section className="card">
      <h2>Partidas con más errores</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Rival</th>
              <th>Apertura</th>
              <th>Resultado</th>
              <th>Errores</th>
              <th>Precisión</th>
            </tr>
          </thead>
          <tbody>
            {stats.worst_games.map((g) => (
              <tr key={g.game_id}>
                <td>{formatDate(g.played_at)}</td>
                <td>
                  <Link to={`/games/${g.game_id}`}>{g.opponent}</Link>
                </td>
                <td className="opening">{g.opening ?? "—"}</td>
                <td>
                  <ResultBadge result={g.outcome} />
                </td>
                <td>
                  <ErrorCountBadges counts={g.counts} />
                </td>
                <td>{formatNumber(g.accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
