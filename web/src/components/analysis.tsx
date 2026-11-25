import type { MouseEvent } from "react";

import { CLASS_LABELS, CLASS_SYMBOLS, evalBarShare, formatPct } from "../format";
import type { Color, Evaluation, GameMove } from "../types";

/** Vertical bar: White's share is the bottom part when the board shows White at the bottom. */
export function EvalBar({ evaluation, orientation }: { evaluation: Evaluation | null; orientation: Color }) {
  if (!evaluation) return <div className="eval-bar eval-bar-empty" aria-hidden="true" />;
  const white = evalBarShare(evaluation.white_win_pct);
  const whiteAtBottom = orientation === "white";
  return (
    <div
      className={`eval-bar ${whiteAtBottom ? "" : "eval-bar-flipped"}`}
      role="img"
      aria-label={`Evaluación ${evaluation.text}, blancas ${formatPct(evaluation.white_win_pct)}`}
      title={`${evaluation.text} · blancas ${formatPct(evaluation.white_win_pct)}`}
    >
      <div className="eval-bar-white" style={{ height: `${white}%` }} />
      <span className="eval-bar-text">{evaluation.text}</span>
    </div>
  );
}

const CHART_W = 600;
const CHART_H = 120;

/** White's win probability after each ply; click to jump to a move. */
export function EvalChart({
  start,
  moves,
  current,
  onSelect,
}: {
  start: Evaluation | null;
  moves: GameMove[];
  current: number;
  onSelect: (ply: number) => void;
}) {
  const points: { ply: number; pct: number }[] = [];
  if (start) points.push({ ply: 0, pct: start.white_win_pct });
  for (const move of moves) {
    if (move.analysis) points.push({ ply: move.ply, pct: move.analysis.eval_after.white_win_pct });
  }
  if (points.length < 2) return null;

  const plies = Math.max(1, moves.length);
  const x = (ply: number) => (ply / plies) * CHART_W;
  const y = (pct: number) => CHART_H - (pct / 100) * CHART_H;
  const line = points.map((p) => `${x(p.ply).toFixed(1)},${y(p.pct).toFixed(1)}`).join(" ");
  const area = `0,${CHART_H} ${line} ${x(points[points.length - 1]!.ply).toFixed(1)},${CHART_H}`;
  const mistakes = moves.filter(
    (m) => m.by_user && m.analysis && m.analysis.classification !== "ok",
  );

  const pickPly = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    onSelect(Math.min(plies, Math.max(0, Math.round(ratio * plies))));
  };

  return (
    <svg
      className="eval-chart"
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      preserveAspectRatio="none"
      onClick={pickPly}
      role="img"
      aria-label="Probabilidad de victoria de las blancas a lo largo de la partida"
    >
      <rect className="eval-chart-bg" x="0" y="0" width={CHART_W} height={CHART_H} />
      <polygon className="eval-chart-area" points={area} />
      <line className="eval-chart-mid" x1="0" x2={CHART_W} y1={CHART_H / 2} y2={CHART_H / 2} />
      <polyline className="eval-chart-line" points={line} vectorEffect="non-scaling-stroke" />
      {mistakes.map((m) => (
        <circle
          key={m.ply}
          className={`eval-chart-dot dot-${m.analysis!.classification}`}
          cx={x(m.ply)}
          cy={y(m.analysis!.eval_after.white_win_pct)}
          r="4"
          vectorEffect="non-scaling-stroke"
        >
          <title>{`${m.label}${m.san}: ${CLASS_LABELS[m.analysis!.classification]}`}</title>
        </circle>
      ))}
      <line
        className="eval-chart-cursor"
        x1={x(current)}
        x2={x(current)}
        y1="0"
        y2={CHART_H}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Moves in pairs ("12. Nf3 Nc6"), coloured by classification. */
export function MoveList({
  moves,
  current,
  onSelect,
}: {
  moves: GameMove[];
  current: number;
  onSelect: (ply: number) => void;
}) {
  const rows: { number: number; white?: GameMove; black?: GameMove }[] = [];
  for (const move of moves) {
    let row = rows[rows.length - 1];
    if (!row || row.number !== move.move_number || (move.color === "white" && row.white)) {
      row = { number: move.move_number };
      rows.push(row);
    }
    row[move.color] = move;
  }

  const cell = (move: GameMove | undefined) => {
    if (!move) return <span className="move-cell move-empty" />;
    const cls = move.analysis?.classification ?? "ok";
    return (
      <button
        type="button"
        className={`move-cell move-${cls} ${move.by_user ? "move-user" : ""} ${
          move.ply === current ? "move-current" : ""
        }`}
        onClick={() => onSelect(move.ply)}
        aria-current={move.ply === current ? "step" : undefined}
        title={cls !== "ok" ? CLASS_LABELS[cls] : undefined}
        data-ply={move.ply}
      >
        {move.san}
        {CLASS_SYMBOLS[cls] && <span className="move-symbol">{CLASS_SYMBOLS[cls]}</span>}
      </button>
    );
  };

  return (
    <ol className="move-list">
      {rows.map((row) => (
        <li key={`${row.number}-${row.white?.ply ?? row.black?.ply}`} className="move-row">
          <span className="move-number">{row.number}.</span>
          {cell(row.white)}
          {cell(row.black)}
        </li>
      ))}
    </ol>
  );
}
