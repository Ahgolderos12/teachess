import type {
  AnalysisResult,
  CoachEvent,
  Color,
  Diagnosis,
  GameDetail,
  GameRow,
  ImportResult,
  Job,
  MoveEvaluation,
  Platform,
  PlayerStats,
  PositionEvaluation,
  Status,
  SyncResult,
  SyncStatus,
  TeacherBoard,
  TeacherInfo,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Human-readable message from a FastAPI error body (`detail` string or validation list). */
export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
        .filter(Boolean);
      if (messages.length) return messages.join(" · ");
    }
  }
  return `Error del servidor (${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("No hay conexión con Teachess. ¿Sigue abierto `teachess serve`?", 0);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(body, response.status), response.status);
  return body as T;
}

const post = <T>(path: string, data: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(data) });

export const api = {
  status: () => request<Status>("/api/status"),
  games: (user?: string) =>
    request<{ games: GameRow[] }>(
      user ? `/api/games?user=${encodeURIComponent(user)}` : "/api/games",
    ).then((r) => r.games),
  game: (id: number) => request<GameDetail>(`/api/games/${id}`),
  stats: (user: string, query = "") =>
    request<PlayerStats>(`/api/users/${encodeURIComponent(user)}/stats${query ? `?${query}` : ""}`),
  diagnosis: (user: string, window = 20) =>
    request<Diagnosis>(`/api/users/${encodeURIComponent(user)}/diagnosis?window=${window}`),
  sync: () => request<SyncStatus>("/api/sync"),
  teacher: () => request<TeacherInfo>("/api/teacher"),
  teacherBoard: () =>
    request<{ board: TeacherBoard | null }>("/api/teacher/board").then((r) => r.board),
  syncNow: () => post<Job<SyncResult>>("/api/sync", {}),
  job: <R>(id: string) => request<Job<R>>(`/api/jobs/${encodeURIComponent(id)}`),
  startImport: (body: {
    platform: Platform;
    user?: string;
    max_games?: number;
    pgn?: string;
    color?: Color | null;
    analyze?: boolean;
  }) => post<Job<ImportResult>>("/api/imports", body),
  startAnalysis: (body: { game_id?: number; user?: string; reanalyze?: boolean }) =>
    post<Job<AnalysisResult>>("/api/analyses", body),
  evaluate: (fen: string, gameId?: number) =>
    post<PositionEvaluation>("/api/engine/evaluate", { fen, game_id: gameId ?? null }),
  evaluateMove: (fen: string, move: string, gameId?: number) =>
    post<MoveEvaluation>("/api/engine/move", { fen, move, game_id: gameId ?? null }),
  createCoachSession: (gameId: number) =>
    post<{ session_id: string }>("/api/coach/sessions", { game_id: gameId }),
};

/** Parse a chunk buffer of Server-Sent Events; returns complete events and the remainder. */
export function parseSse(buffer: string): { events: CoachEvent[]; rest: string } {
  const events: CoachEvent[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data: "))
      .map((line) => line.slice(6))
      .join("\n");
    if (!data) continue;
    try {
      events.push(JSON.parse(data) as CoachEvent);
    } catch {
      // Ignore malformed events instead of breaking the chat.
    }
  }
  return { events, rest };
}

/** Send a question to the coach and stream its answer event by event. */
export async function askCoach(
  sessionId: string,
  text: string,
  onEvent: (event: CoachEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/coach/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok || !response.body) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(errorMessage(body, response.status), response.status);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }
  parseSse(buffer + "\n\n").events.forEach(onEvent);
}
