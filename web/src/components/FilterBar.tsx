import { useEffect, useState } from "react";

import {
  DAY_BLOCK_LABELS,
  describeFilter,
  isEmptyFilter,
  OUTCOME_FILTER_LABELS,
  patchFilter,
  type StatsFilter,
  WEEKDAY_LABELS,
} from "../filters";
import { COLOR_LABELS, formatTimeControl, TERMINATION_LABELS, TIME_CLASS_LABELS } from "../format";
import type { FilterOptions } from "../types";

const RIVAL_OPTIONS: [string, number | undefined, number | undefined][] = [
  ["rival 100+ por debajo", undefined, -100],
  ["rival 26-99 por debajo", -99, -26],
  ["rival parecido (±25)", -25, 25],
  ["rival 26-99 por encima", 26, 99],
  ["rival 100+ por encima", 100, undefined],
];

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="filter-field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Todas</option>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Controls for one group of games (A or B in compare mode). */
export function FilterBar({
  filter,
  options,
  onChange,
  title,
  matching,
}: {
  filter: StatsFilter;
  options: FilterOptions | null;
  onChange: (filter: StatsFilter) => void;
  title?: string;
  matching?: number;
}) {
  const set = (patch: Partial<StatsFilter>) => onChange(patchFilter(filter, patch));
  const [opening, setOpening] = useState(filter.opening ?? "");
  useEffect(() => setOpening(filter.opening ?? ""), [filter.opening]);
  const rival = RIVAL_OPTIONS.findIndex(([, min, max]) => min === filter.min_gap && max === filter.max_gap);
  const chips = describeFilter(filter);
  const datalistId = `openings-${title ?? "a"}`;

  return (
    <div className="filter-bar card">
      {(title || matching !== undefined) && (
        <div className="filter-bar-header">
          {title && <strong>{title}</strong>}
          {matching !== undefined && <span className="muted small">{matching} partidas</span>}
        </div>
      )}
      <div className="filter-grid">
        <Select
          label="Ritmo"
          value={filter.time_class ?? ""}
          options={(options?.time_classes ?? []).map((tc) => [tc, TIME_CLASS_LABELS[tc] ?? tc])}
          onChange={(v) => set({ time_class: v || undefined })}
        />
        <Select
          label="Control"
          value={filter.time_control ?? ""}
          options={(options?.time_controls ?? []).map((tc) => [tc, formatTimeControl(tc)])}
          onChange={(v) => set({ time_control: v || undefined })}
        />
        <Select
          label="Color"
          value={filter.color ?? ""}
          options={[
            ["white", COLOR_LABELS.white],
            ["black", COLOR_LABELS.black],
          ]}
          onChange={(v) => set({ color: v || undefined })}
        />
        <Select
          label="Resultado"
          value={filter.outcome ?? ""}
          options={Object.entries(OUTCOME_FILTER_LABELS).map(([k, v]) => [k, v])}
          onChange={(v) => set({ outcome: v || undefined })}
        />
        <Select
          label="Fin"
          value={filter.termination ?? ""}
          options={(options?.terminations ?? []).map((t) => [t, TERMINATION_LABELS[t] ?? t])}
          onChange={(v) => set({ termination: v || undefined })}
        />
        <label className="filter-field filter-wide">
          <span>Apertura</span>
          <input
            type="search"
            list={datalistId}
            value={opening}
            placeholder="Buscar: siciliana, Caro Kann…"
            onChange={(e) => setOpening(e.target.value)}
            onBlur={() => set({ opening: opening.trim() || undefined })}
            onKeyDown={(e) => {
              if (e.key === "Enter") set({ opening: opening.trim() || undefined });
            }}
          />
          <datalist id={datalistId}>
            {(options?.openings ?? []).map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </label>
        <Select
          label="Rival"
          value={rival >= 0 ? String(rival) : ""}
          options={RIVAL_OPTIONS.map(([label], index) => [String(index), label])}
          onChange={(v) => {
            const option = v === "" ? undefined : RIVAL_OPTIONS[Number(v)];
            set({ min_gap: option?.[1], max_gap: option?.[2] });
          }}
        />
        <Select
          label="Día"
          value={filter.weekday === undefined ? "" : String(filter.weekday)}
          options={WEEKDAY_LABELS.map((name, index) => [String(index), name])}
          onChange={(v) => set({ weekday: v === "" ? undefined : Number(v) })}
        />
        <Select
          label="Hora"
          value={filter.day_block === undefined ? "" : String(filter.day_block)}
          options={Object.entries(DAY_BLOCK_LABELS).map(([k, v]) => [k, v])}
          onChange={(v) => set({ day_block: v === "" ? undefined : Number(v) })}
        />
        <label className="filter-field">
          <span>Desde</span>
          <input
            type="date"
            value={filter.since ?? ""}
            min={options?.first_date ?? undefined}
            max={options?.last_date ?? undefined}
            onChange={(e) => set({ since: e.target.value || undefined })}
          />
        </label>
        <label className="filter-field">
          <span>Hasta</span>
          <input
            type="date"
            value={filter.until ?? ""}
            min={options?.first_date ?? undefined}
            max={options?.last_date ?? undefined}
            onChange={(e) => set({ until: e.target.value || undefined })}
          />
        </label>
        <Select
          label="Partidas"
          value={filter.last ? String(filter.last) : ""}
          options={["10", "20", "50", "100"].map((n) => [n, `últimas ${n}`])}
          onChange={(v) => set({ last: v ? Number(v) : undefined, offset: undefined })}
        />
      </div>
      {!isEmptyFilter(filter) && (
        <div className="filter-chips">
          {chips.map((chip) => (
            <button
              key={chip.label}
              type="button"
              className="chip chip-removable"
              onClick={() => set(chip.remove)}
              title="Quitar este filtro"
            >
              {chip.label} ×
            </button>
          ))}
          <button type="button" className="link-button small" onClick={() => onChange({})}>
            Quitar filtros
          </button>
        </div>
      )}
    </div>
  );
}
