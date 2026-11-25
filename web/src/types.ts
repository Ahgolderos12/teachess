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
  kind: "import" | "analysis" | "sync";
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

export type Outcome = "win" | "draw" | "loss";
export type TimeClass = "bullet" | "blitz" | "rapid" | "daily";

export interface ResultRecord {
  games: number;
  wins: number;
  draws: number;
  losses: number;
  points: number;
  score_pct: number | null;
}

export interface KeyedRecord extends ResultRecord {
  key: string;
}

export interface PhaseRate {
  moves: number;
  serious_errors: number;
  serious_per_100: number | null;
  avg_win_loss_pct: number | null;
  counts?: ErrorCounts;
}

export interface PlayerStats {
  user: string;
  games_total: number;
  games_analysed: number;
  games_pending: number;
  summary: {
    record: ResultRecord;
    acpl: number | null;
    accuracy: number | null;
    avg_moves: number | null;
    ratings: {
      time_class: TimeClass;
      games: number;
      latest: number;
      peak: number;
      lowest: number;
      change: number;
      avg_opponent: number | null;
    }[];
    streaks: {
      current: { outcome: Outcome; games: number } | null;
      longest_win: number;
      longest_loss: number;
    };
  };
  results: {
    by_color: Record<Color, ResultRecord>;
    by_time_class: KeyedRecord[];
    by_time_control: KeyedRecord[];
    by_rating_diff: KeyedRecord[];
    by_weekday: KeyedRecord[];
    by_time_of_day: KeyedRecord[];
  };
  terminations: Record<Outcome, Record<string, number>>;
  errors: {
    moves: number;
    counts: ErrorCounts;
    per_game: Record<ErrorClass, number | null>;
    by_phase: Record<Phase, PhaseRate>;
    games_without_serious_errors: number;
  };
  openings: {
    opening: string;
    color: Color;
    games: number;
    wins: number;
    draws: number;
    losses: number;
    points: number;
    score_pct: number | null;
    accuracy: number | null;
    acpl: number | null;
    decided_early: number;
    last_game_id: number;
  }[];
  time: {
    avg_seconds_by_phase: Record<Phase, number | null>;
    think_time: { key: string; moves: number; serious_errors: number; serious_pct: number | null }[];
    low_clock_moves_pct: number | null;
    serious_per_100_low_clock: number | null;
    serious_per_100_otherwise: number | null;
    losses_on_time: number;
    wins_on_time: number;
    avg_clock_left_pct_end_of_losses: number | null;
  };
  decisive_errors: {
    not_won: number;
    with_decisive_error: number;
    by_move_number: { key: string; games: number }[];
    by_phase: Partial<Record<Phase, number>>;
    avg_move_number: number | null;
    avg_seconds_spent: number | null;
  };
  conversion: {
    winning_games: number;
    converted: number;
    conversion_pct: number | null;
    losing_games: number;
    saved: number;
    save_pct: number | null;
  };
  duration: Record<Outcome, number | null>;
  monthly: (ResultRecord & { month: string; accuracy: number | null; acpl: number | null })[];
  timeline: {
    game_id: number;
    played_at: string | null;
    outcome: Outcome;
    rating: number | null;
    time_control: string | null;
    time_class: TimeClass;
    accuracy: number | null;
    acpl: number | null;
    blunders: number | null;
    mistakes: number | null;
  }[];
  worst_games: {
    game_id: number;
    played_at: string | null;
    opponent: string;
    user_color: Color;
    outcome: Outcome;
    opening: string | null;
    counts: ErrorCounts;
    accuracy: number | null;
    acpl: number | null;
  }[];
}

export interface Finding {
  kind: string;
  title: string;
  summary: string;
  lesson: string;
  points_lost: number;
  games_affected: number;
  evidence: { game_id: number; move?: string }[];
}

export interface Diagnosis {
  user: string;
  games_total: number;
  games_analysed: number;
  window: { games: number; from: string | null; to: string | null };
  findings: Finding[];
  notes: string[];
}

export interface SyncResult {
  platforms: { platform: Platform; user: string; new?: number; analyzed?: number; error?: string }[];
  new: number;
  analyzed: number;
}

export interface SyncStatus {
  configured: boolean;
  interval_hours: number | null;
  next_run_at: number | null; // epoch seconds
  job: Job<SyncResult> | null;
  users: Partial<Record<Platform, string>>;
}

export interface TeacherInfo {
  available: boolean;
  reason: string | null;
  token: string | null;
  manual_command: string;
}

export interface TeacherBoard {
  fen: string;
  orientation: Color;
  arrow: { uci: string; san: string } | null;
  caption: string;
  updated_at: string;
}

export type TerminalMessage =
  | { type: "output"; data: string }
  | { type: "exit"; code: number };
