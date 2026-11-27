import { formatNumber, PHASE_LABELS, PHASES } from "../format";
import type { PlayerStats } from "../types";

interface Metric {
  label: string;
  value: (s: PlayerStats) => number | null | undefined;
  digits?: number;
  unit?: string;
  better?: "higher" | "lower"; // to colour the difference
  hint?: string;
}

const METRICS: Metric[] = [
  { label: "Partidas", value: (s) => s.summary.record.games, digits: 0 },
  { label: "Puntos", value: (s) => s.summary.record.score_pct, digits: 0, unit: " %", better: "higher" },
  { label: "Precisión media", value: (s) => s.summary.accuracy, better: "higher" },
  { label: "ACPL", value: (s) => s.summary.acpl, digits: 0, better: "lower", hint: "Pérdida media por jugada" },
  { label: "Errores graves por partida", value: (s) => s.errors.per_game.blunder, digits: 2, better: "lower" },
  { label: "Errores por partida", value: (s) => s.errors.per_game.mistake, digits: 2, better: "lower" },
  ...PHASES.map(
    (phase): Metric => ({
      label: `Errores serios / 100 en ${PHASE_LABELS[phase].toLowerCase()}`,
      value: (s) => s.errors.by_phase[phase].serious_per_100,
      better: "lower",
    }),
  ),
  {
    label: "Ventajas ganadoras convertidas",
    value: (s) => s.conversion.conversion_pct,
    digits: 0,
    unit: " %",
    better: "higher",
  },
  { label: "Posiciones perdidas salvadas", value: (s) => s.conversion.save_pct, digits: 0, unit: " %", better: "higher" },
  {
    label: "Jugada media del error decisivo",
    value: (s) => s.decisive_errors.avg_move_number,
    digits: 0,
    better: "higher",
    hint: "Cuanto más tarde, más aguantas la partida",
  },
  ...PHASES.map(
    (phase): Metric => ({
      label: `Segundos por jugada en ${PHASE_LABELS[phase].toLowerCase()}`,
      value: (s) => s.time.avg_seconds_by_phase[phase],
      unit: " s",
    }),
  ),
  {
    label: "Jugadas con menos del 10 % del reloj",
    value: (s) => s.time.low_clock_moves_pct,
    unit: " %",
    better: "lower",
  },
  { label: "Jugadas por partida", value: (s) => s.summary.avg_moves, digits: 0 },
];

function format(metric: Metric, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${formatNumber(value, metric.digits ?? 1)}${metric.unit ?? ""}`;
}

/** Key figures of two groups of games side by side, with the better one highlighted. */
export function CompareView({
  a,
  b,
  labelA,
  labelB,
}: {
  a: PlayerStats;
  b: PlayerStats;
  labelA: string;
  labelB: string;
}) {
  return (
    <section className="card">
      <h2>Comparación</h2>
      <div className="table-wrap">
        <table className="table compare-table">
          <thead>
            <tr>
              <th />
              <th>
                <span className="group-tag group-a">A</span> {labelA}
              </th>
              <th>
                <span className="group-tag group-b">B</span> {labelB}
              </th>
              <th>Diferencia (A − B)</th>
            </tr>
          </thead>
          <tbody>
            {METRICS.map((metric) => {
              const va = metric.value(a);
              const vb = metric.value(b);
              const both = va !== null && va !== undefined && vb !== null && vb !== undefined;
              const diff = both ? va - vb : null;
              let tone = "";
              if (diff && metric.better) {
                const aBetter = metric.better === "higher" ? diff > 0 : diff < 0;
                tone = aBetter ? "better-a" : "better-b";
              }
              return (
                <tr key={metric.label} title={metric.hint}>
                  <td>{metric.label}</td>
                  <td className={tone === "better-a" ? "cell-better" : ""}>{format(metric, va)}</td>
                  <td className={tone === "better-b" ? "cell-better" : ""}>{format(metric, vb)}</td>
                  <td className="muted">
                    {diff === null ? "—" : `${diff > 0 ? "+" : ""}${format(metric, diff)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">En verde, el grupo que sale mejor en cada fila (cuando una dirección es mejor).</p>
    </section>
  );
}
