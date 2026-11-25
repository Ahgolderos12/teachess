// Shapes returned by the Teachess API (src/teachess/api/serializers.py and app.py).

export type Classification = "ok" | "inaccuracy" | "mistake" | "blunder";
export type ErrorClass = Exclude<Classification, "ok">;
export type Phase = "opening" | "middlegame" | "endgame";
export type Color = "white" | "black";
export type Platform = "chesscom" | "lichess" | "pgn";
export type UserResult = "win" | "loss" | "draw" | "unknown";

export type ErrorCounts = Record<ErrorClass, number>;

export interface Status {
  version: string;
  stockfish: boolean;
  engine_depth: number;
  default_users: Partial<Record<Platform, string | null>>;
  users: string[];
  games: number;
  games_analyzed: number;
  coach: { web_enabled: boolean; model: string; mcp_command: string };
}

export interface GameSummary {
  acpl: number | null;
  counts: ErrorCounts;
  user_moves: number;
}

export interface GameRow {
  id: number;
  platform: Platform;
  username: string;
  white: string;
  black: string;
  opponent: string;
  user_color: Color;
  result: string;
  user_result: UserResult;
  played_at: string | null;
  time_control: string | null;
  url: string | null;
  opening: string | null;
  analyzed_depth: number | null;
  summary: GameSummary | null;
}

export interface Evaluation {
  text: string;
  cp: number | null;
  mate: number | null;
  white_win_pct: number;
  depth: number;
}

export interface MoveAnalysis {
  eval_before: Evaluation;
  eval_after: Evaluation;
  best_move_san: string | null;
  best_move_uci: string | null;
  engine_line: string;
  win_loss: number;
  cp_loss: number;
  classification: Classification;
  phase: Phase;
}

export interface GameMove {
  ply: number;
  move_number: number;
  color: Color;
  by_user: boolean;
  label: string;
  san: string;
  uci: string;
  fen_before: string;
  fen_after: string;
  clock_seconds: number | null;
  analysis: MoveAnalysis | null;
}

export interface GameDetail extends GameRow {
  start_fen: string;
  start_eval: Evaluation | null;
  moves: GameMove[];
}

export interface UserReport {
  username: string;
  known_user: boolean;
  games_analyzed: number;
  games_pending: number;
  acpl: number | null;
  counts: ErrorCounts;
  by_phase: Record<Phase, ErrorCounts>;
  results: Record<UserResult, number>;
  worst_games: GameRow[];
}

export type JobStatus = "queued" | "running" | "done" | "error";

export interface ImportResult {
  username: string;
  new: number;
  existing: number;
  skipped: number;
  analysis?: AnalysisResult;
  analysis_error?: string;
}

export interface AnalysisResult {
  analyzed: number;
  depth: number;
  game_ids: number[];
}

export interface Job<R = unknown> {
  id: string;
  kind: "import" | "analysis";
  status: JobStatus;
  current: number;
  total: number;
  message: string;
  result: R | null;
  error: string | null;
  created_at: number;
}

export interface PositionEvaluation {
  fen: string;
  side_to_move: Color;
  game_over?: boolean;
  result?: string;
  eval?: string;
  white_win_pct?: number;
  best_move?: string | null;
  engine_line?: string;
  depth?: number;
}

export interface MoveEvaluation {
  move: string;
  best_move: string | null;
  is_best: boolean;
  eval_before: string;
  eval_after: string;
  win_loss_pct: number;
  cp_loss: number;
  classification: Classification;
  fen_after: string;
  best_reply_line: string;
  depth: number;
}

export type CoachEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string }
  | {
      type: "done";
      refused: boolean;
      truncated: boolean;
      usage: { input_tokens: number; output_tokens: number; cache_read_tokens: number };
    }
  | { type: "error"; message: string };
