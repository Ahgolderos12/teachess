import type { Classification, ErrorClass, Phase, Platform, UserResult } from "./types";

export const ERROR_CLASSES: ErrorClass[] = ["blunder", "mistake", "inaccuracy"];
export const PHASES: Phase[] = ["opening", "middlegame", "endgame"];

export const CLASS_LABELS: Record<Classification, string> = {
  ok: "correcta",
  inaccuracy: "imprecisión",
  mistake: "error",
  blunder: "error grave",
};

export const CLASS_PLURALS: Record<ErrorClass, string> = {
  inaccuracy: "Imprecisiones",
  mistake: "Errores",
  blunder: "Errores graves",
};

export const CLASS_SYMBOLS: Record<Classification, string> = {
  ok: "",
  inaccuracy: "?!",
  mistake: "?",
  blunder: "??",
};

export const PHASE_LABELS: Record<Phase, string> = {
  opening: "Apertura",
  middlegame: "Medio juego",
  endgame: "Final",
};

export const RESULT_LABELS: Record<UserResult, string> = {
  win: "Victoria",
  loss: "Derrota",
  draw: "Tablas",
  unknown: "Sin terminar",
};

export const PLATFORM_LABELS: Record<Platform, string> = {
  chesscom: "Chess.com",
  lichess: "Lichess",
  pgn: "PGN",
};

export const TOOL_LABELS: Record<string, string> = {
  get_game_summary: "resumen de la partida",
  get_critical_moments: "momentos críticos",
  get_move: "jugada de la partida",
  evaluate_position: "Stockfish: posición",
  evaluate_move: "Stockfish: jugada",
};

/** "2026-10-14T13:30:31+00:00" -> "14/10/2026". */
export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** PGN TimeControl -> "10+5", "3 min", "Diaria"… */
export function formatTimeControl(tc: string | null): string {
  if (!tc || tc === "-" || tc === "?") return "—";
  if (tc.includes("/")) return "Diaria";
  const [baseText, incrementText] = tc.split("+");
  const base = Number(baseText);
  const increment = Number(incrementText ?? 0);
  if (!Number.isFinite(base) || !Number.isFinite(increment)) return tc;
  const baseLabel = base >= 60 ? `${+(base / 60).toFixed(1)}` : `${base}s`;
  if (increment) return `${baseLabel}+${increment}`;
  return base >= 60 ? `${baseLabel} min` : baseLabel;
}

/** Remaining clock in seconds -> "9:58" or "1:02:03". */
export function formatClock(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function formatAcpl(acpl: number | null | undefined): string {
  return acpl === null || acpl === undefined ? "—" : String(Math.round(acpl));
}

export function formatPct(value: number): string {
  return `${value.toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`;
}

/** Split a UCI move into board squares for arrows: "e2e4" -> ["e2", "e4"]. */
export function uciSquares(uci: string | null | undefined): [string, string] | null {
  if (!uci || !/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)) return null;
  return [uci.slice(0, 2), uci.slice(2, 4)];
}

/** Share of the evaluation bar for White (0-100), clamped so both sides stay visible. */
export function evalBarShare(whiteWinPct: number): number {
  return Math.min(97, Math.max(3, whiteWinPct));
}

/** Scroll `container` so `element` is visible, without scrolling the page itself. */
export function scrollWithin(container: HTMLElement | null, element: HTMLElement | null): void {
  if (!container || !element) return;
  const box = container.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const top = rect.top - box.top + container.scrollTop;
  const bottom = top + rect.height;
  if (top < container.scrollTop) container.scrollTop = top;
  else if (bottom > container.scrollTop + container.clientHeight) {
    container.scrollTop = bottom - container.clientHeight;
  }
}

export const TIME_CLASS_LABELS: Record<string, string> = {
  bullet: "Bala",
  blitz: "Blitz",
  rapid: "Rápidas",
  daily: "Diarias",
};

export const TERMINATION_LABELS: Record<string, string> = {
  checkmate: "jaque mate",
  resignation: "abandono",
  time: "tiempo",
  abandoned: "partida abandonada",
  agreement: "acuerdo",
  repetition: "repetición",
  stalemate: "ahogado",
  insufficient: "material insuficiente",
  other: "otro motivo",
};

export const COLOR_LABELS: Record<"white" | "black", string> = { white: "Blancas", black: "Negras" };

/** Number with Spanish formatting, or a dash when missing. */
export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("es-ES", { maximumFractionDigits: digits });
}

/** Moving average over the last `size` values, skipping nulls. */
export function movingAverage(values: (number | null)[], size: number): (number | null)[] {
  return values.map((_, index) => {
    const window = values.slice(Math.max(0, index - size + 1), index + 1).filter(
      (v): v is number => v !== null,
    );
    return window.length ? window.reduce((a, b) => a + b, 0) / window.length : null;
  });
}
