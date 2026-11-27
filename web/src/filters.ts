import { COLOR_LABELS, formatTimeControl, TERMINATION_LABELS, TIME_CLASS_LABELS } from "./format";

/** Filters of the Statistics page; mirrors patterns.filters.GameFilter. */
export interface StatsFilter {
  time_class?: string;
  time_control?: string;
  color?: string;
  outcome?: string;
  termination?: string;
  opening?: string;
  since?: string;
  until?: string;
  min_gap?: number;
  max_gap?: number;
  weekday?: number;
  day_block?: number;
  last?: number;
  offset?: number;
}

const NUMBER_KEYS = ["min_gap", "max_gap", "weekday", "day_block", "last", "offset"] as const;
const TEXT_KEYS = [
  "time_class",
  "time_control",
  "color",
  "outcome",
  "termination",
  "opening",
  "since",
  "until",
] as const;
export const FILTER_KEYS = [...TEXT_KEYS, ...NUMBER_KEYS] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

export const WEEKDAY_LABELS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
export const DAY_BLOCK_LABELS: Record<number, string> = {
  0: "madrugada",
  6: "mañana",
  12: "tarde",
  18: "noche",
};
export const OUTCOME_FILTER_LABELS: Record<string, string> = {
  win: "victorias",
  draw: "tablas",
  loss: "derrotas",
};

/** Read a filter from URL params; `prefix` separates group B ("b_") in compare mode. */
export function readFilter(params: URLSearchParams, prefix = ""): StatsFilter {
  const filter: StatsFilter = {};
  for (const key of TEXT_KEYS) {
    const value = params.get(prefix + key);
    if (value) filter[key] = value;
  }
  for (const key of NUMBER_KEYS) {
    const value = params.get(prefix + key);
    if (value !== null && value !== "" && Number.isFinite(Number(value))) filter[key] = Number(value);
  }
  return filter;
}

/** Write a filter into URL params (replacing that group's keys). */
export function writeFilter(params: URLSearchParams, filter: StatsFilter, prefix = ""): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of FILTER_KEYS) next.delete(prefix + key);
  for (const key of FILTER_KEYS) {
    const value = filter[key];
    if (value !== undefined && value !== "" && !(key === "offset" && value === 0)) {
      next.set(prefix + key, String(value));
    }
  }
  return next;
}

/** Query string for the API. */
export function filterQuery(filter: StatsFilter): string {
  return writeFilter(new URLSearchParams(), filter).toString();
}

export function isEmptyFilter(filter: StatsFilter): boolean {
  return FILTER_KEYS.every((key) => filter[key] === undefined);
}

/** Merge a patch; `undefined` values remove a key. */
export function patchFilter(filter: StatsFilter, patch: Partial<StatsFilter>): StatsFilter {
  const next: StatsFilter = { ...filter };
  for (const [key, value] of Object.entries(patch) as [FilterKey, StatsFilter[FilterKey]][]) {
    if (value === undefined || value === "") delete next[key];
    else (next as Record<string, unknown>)[key] = value;
  }
  return next;
}

function gapLabel(min?: number, max?: number): string {
  if (min !== undefined && max !== undefined) return `rival entre ${min} y ${max}`;
  if (min !== undefined) return `rival ${min}+`;
  return `rival hasta ${max}`;
}

/** Human labels for the active filters, each with the patch that removes it. */
export function describeFilter(filter: StatsFilter): { label: string; remove: Partial<StatsFilter> }[] {
  const chips: { label: string; remove: Partial<StatsFilter> }[] = [];
  const add = (label: string, remove: Partial<StatsFilter>) => chips.push({ label, remove });
  if (filter.time_class) add(TIME_CLASS_LABELS[filter.time_class] ?? filter.time_class, { time_class: undefined });
  if (filter.time_control) add(formatTimeControl(filter.time_control), { time_control: undefined });
  if (filter.color) add(`con ${(COLOR_LABELS[filter.color as "white" | "black"] ?? filter.color).toLowerCase()}`, { color: undefined });
  if (filter.outcome) add(OUTCOME_FILTER_LABELS[filter.outcome] ?? filter.outcome, { outcome: undefined });
  if (filter.termination) add(`por ${TERMINATION_LABELS[filter.termination] ?? filter.termination}`, { termination: undefined });
  if (filter.opening) add(`apertura «${filter.opening}»`, { opening: undefined });
  if (filter.since) add(`desde ${filter.since}`, { since: undefined });
  if (filter.until) add(`hasta ${filter.until}`, { until: undefined });
  if (filter.min_gap !== undefined || filter.max_gap !== undefined) {
    add(gapLabel(filter.min_gap, filter.max_gap), { min_gap: undefined, max_gap: undefined });
  }
  if (filter.weekday !== undefined) add(WEEKDAY_LABELS[filter.weekday] ?? "", { weekday: undefined });
  if (filter.day_block !== undefined) add(DAY_BLOCK_LABELS[filter.day_block] ?? "", { day_block: undefined });
  if (filter.last) {
    add(filter.offset ? `las ${filter.last} anteriores a las ${filter.offset} últimas` : `últimas ${filter.last}`, {
      last: undefined,
      offset: undefined,
    });
  }
  return chips;
}

/** Ready-made comparisons: [label, group A, group B]. */
export const COMPARE_PRESETS: [string, StatsFilter, StatsFilter][] = [
  ["Blancas vs negras", { color: "white" }, { color: "black" }],
  ["Últimas 20 vs 20 anteriores", { last: 20 }, { last: 20, offset: 20 }],
  ["Rápidas vs blitz", { time_class: "rapid" }, { time_class: "blitz" }],
  ["Tarde vs noche", { day_block: 12 }, { day_block: 18 }],
];
