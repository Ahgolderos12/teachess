import type React from "react";
import { useState } from "react";

import { formatNumber } from "../format";
import type { ResultRecord } from "../types";

/** Win / draw / loss as one thin stacked bar, with the score next to it. */
/** Props that make a chart row a filter: click (or Enter) to filter by it. */
export interface Selectable {
  onSelect?: () => void;
  active?: boolean;
}

function selectableProps({ onSelect, active }: Selectable, base: string) {
  if (!onSelect) return { className: base };
  return {
    className: `${base} selectable ${active ? "selected" : ""}`,
    role: "button",
    tabIndex: 0,
    "aria-pressed": Boolean(active),
    onClick: onSelect,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect();
      }
    },
  };
}

export function ResultBar({
  record,
  label,
  ...selectable
}: { record: ResultRecord; label: string } & Selectable) {
  const { games, wins, draws, losses } = record;
  const tip = `${label}: ${wins} V · ${draws} T · ${losses} D${selectable.onSelect ? " · clic para filtrar" : ""}`;
  return (
    <div {...selectableProps(selectable, "result-row")} title={tip}>
      <span className="result-row-label">{label}</span>
      <div className="result-bar" role="img" aria-label={tip}>
        {games === 0 ? (
          <span className="result-bar-empty" />
        ) : (
          (
            [
              ["win", wins],
              ["draw", draws],
              ["loss", losses],
            ] as const
          ).map(([kind, value]) =>
            value ? (
              <span
                key={kind}
                className={`result-seg seg-${kind}`}
                style={{ flexGrow: value }}
              />
            ) : null,
          )
        )}
      </div>
      <span className="result-row-value">
        {games ? `${record.score_pct} %` : "—"}
        <span className="muted small"> · {games}</span>
      </span>
    </div>
  );
}

export function ResultLegend() {
  return (
    <p className="legend muted small">
      <span className="legend-item">
        <span className="legend-swatch seg-win" /> Victorias
      </span>
      <span className="legend-item">
        <span className="legend-swatch seg-draw" /> Tablas
      </span>
      <span className="legend-item">
        <span className="legend-swatch seg-loss" /> Derrotas
      </span>
      <span className="legend-item">% de puntos · partidas</span>
    </p>
  );
}

/** Horizontal bars for one measure; the value is printed at the end of each bar. */
export function BarList({
  rows,
  format = (v) => formatNumber(v),
  className = "seg-accent",
}: {
  rows: ({ key: string; value: number | null; note?: string } & Selectable)[];
  format?: (value: number) => string;
  className?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value ?? 0));
  return (
    <div className="bar-list">
      {rows.map((row) => (
        <div key={row.key} {...selectableProps(row, "result-row")} title={row.note ?? undefined}>
          <span className="result-row-label">{row.key}</span>
          <div className="result-bar">
            {row.value ? (
              <span className={`result-seg ${className}`} style={{ width: `${(row.value / max) * 100}%` }} />
            ) : null}
          </div>
          <span className="result-row-value">
            {row.value === null ? "—" : format(row.value)}
            {row.note && <span className="muted small"> · {row.note}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export interface LinePoint {
  label: string; // tooltip title (date, opponent…)
  value: number | null;
  detail?: string;
}

/** Single-series line chart with a hover crosshair and tooltip. */
export function LineChart({
  points,
  smooth,
  format = (v) => formatNumber(v),
  height = 180,
  ariaLabel,
}: {
  points: LinePoint[];
  smooth?: (number | null)[]; // optional trend line drawn on top (e.g. moving average)
  format?: (value: number) => string;
  height?: number;
  ariaLabel: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { top: 12, right: 12, bottom: 20, left: 44 };
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);
  if (values.length < 2) return <p className="muted">Faltan datos para la gráfica.</p>;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const margin = (max - min) * 0.08;
  min -= margin;
  max += margin;
  const x = (i: number) =>
    pad.left + (points.length === 1 ? 0 : (i / (points.length - 1)) * (width - pad.left - pad.right));
  const y = (v: number) => pad.top + (1 - (v - min) / (max - min)) * (height - pad.top - pad.bottom);
  const path = (series: (number | null)[]) =>
    series
      .map((v, i) => (v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`))
      .filter(Boolean)
      .map((p, i) => `${i ? "L" : "M"}${p}`)
      .join(" ");
  const ticks = [min + margin, (min + max) / 2, max - margin];
  const hovered = hover !== null ? points[hover] : null;

  return (
    <div className="line-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - box.left) / box.width) * width;
          const ratio = (px - pad.left) / (width - pad.left - pad.right);
          setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
        }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} />
            <text className="chart-tick" x={pad.left - 6} y={y(t) + 4} textAnchor="end">
              {format(t)}
            </text>
          </g>
        ))}
        <path className={smooth ? "chart-line chart-line-faint" : "chart-line"} d={path(points.map((p) => p.value))} />
        {smooth && <path className="chart-line" d={path(smooth)} />}
        {hover !== null && hovered?.value !== null && hovered && (
          <g>
            <line
              className="chart-cursor"
              x1={x(hover)}
              x2={x(hover)}
              y1={pad.top}
              y2={height - pad.bottom}
            />
            <circle className="chart-dot" cx={x(hover)} cy={y(hovered.value as number)} r={4} />
          </g>
        )}
      </svg>
      {hovered && (
        <div className="chart-tooltip" style={{ left: `${(x(hover ?? 0) / width) * 100}%` }}>
          <strong>{hovered.value === null ? "—" : format(hovered.value)}</strong>
          {smooth && hover !== null && smooth[hover] !== null && (
            <span className="muted"> · media {format(smooth[hover] as number)}</span>
          )}
          <br />
          <span className="muted small">
            {hovered.label}
            {hovered.detail ? ` · ${hovered.detail}` : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/** Big number with a caption: for single headline figures. */
export function StatTile({
  value,
  label,
  hint,
  tone,
}: {
  value: string;
  label: string;
  hint?: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className={`stat card ${tone ? `stat-tone-${tone}` : ""}`} title={hint}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
