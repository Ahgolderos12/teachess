import { Chess } from "chess.js";
import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Chessboard, type Arrow } from "react-chessboard";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import { EvalBar, EvalChart, MoveList } from "../components/analysis";
import { CoachPanel } from "../components/CoachPanel";
import {
  Alert,
  ClassBadge,
  ErrorCountBadges,
  JobProgress,
  Loading,
  ResultBadge,
} from "../components/common";
import {
  CLASS_LABELS,
  formatAcpl,
  formatClock,
  formatDate,
  formatPct,
  formatTimeControl,
  PHASE_LABELS,
  PLATFORM_LABELS,
  scrollWithin,
  uciSquares,
} from "../format";
import { useAsync } from "../hooks";
import { useStatus } from "../status";
import type {
  AnalysisResult,
  Color,
  Evaluation,
  GameDetail,
  GameMove,
  Job,
  MoveEvaluation,
  PositionEvaluation,
} from "../types";

const PLAYED_ARROW = "rgba(214, 69, 65, 0.85)";
const BEST_ARROW = "rgba(46, 160, 67, 0.9)";
const LAST_MOVE: CSSProperties = { background: "rgba(255, 210, 0, 0.38)" };

export function GamePage() {
  const { id } = useParams();
  const gameId = Number(id);
  const game = useAsync(
    () =>
      Number.isInteger(gameId) && gameId > 0
        ? api.game(gameId)
        : Promise.reject(new Error("Identificador de partida no válido.")),
    [gameId],
  );

  if (game.error) {
    return (
      <Alert kind="error">
        {game.error} <Link to="/">Volver a tus partidas</Link>
      </Alert>
    );
  }
  if (!game.data) return <Loading label="Cargando la partida…" />;
  return <GameView key={game.data.id} game={game.data} reload={game.reload} />;
}

interface ExplorerState {
  fens: string[]; // fens[0] is where exploring started
  sans: string[];
  moveEval: MoveEvaluation | null;
  positionEval: PositionEvaluation | null;
  loading: boolean;
  error: string | null;
}

function GameView({ game, reload }: { game: GameDetail; reload: () => void }) {
  const { status, reload: reloadStatus } = useStatus();
  const moves = game.moves;
  const analyzed = game.analyzed_depth !== null;
  const [current, setCurrent] = useState(() => firstCriticalPly(game) ?? 0);
  const [showBest, setShowBest] = useState(() => firstCriticalPly(game) !== null);
  const [orientation, setOrientation] = useState<Color>(game.user_color);
  const [explorer, setExplorer] = useState<ExplorerState | null>(null);
  const [job, setJob] = useState<Job<AnalysisResult> | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const move: GameMove | undefined = current > 0 ? moves[current - 1] : undefined;
  const analysis = move?.analysis ?? null;
  const canShowBest = Boolean(analysis && analysis.best_move_uci && analysis.best_move_uci !== move?.uci);

  const goTo = useCallback(
    (ply: number, best = false) => {
      setExplorer(null);
      setCurrent(Math.min(moves.length, Math.max(0, ply)));
      setShowBest(best);
    },
    [moves.length],
  );

  // Keyboard navigation, except while typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (explorer) return;
      const next: Record<string, number> = {
        ArrowLeft: current - 1,
        ArrowRight: current + 1,
        Home: 0,
        End: moves.length,
      };
      const ply = next[event.key];
      if (ply === undefined) return;
      event.preventDefault();
      goTo(ply);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, moves.length, explorer, goTo]);

  // Keep the current move visible in the move list.
  useEffect(() => {
    scrollWithin(
      document.querySelector<HTMLElement>(".move-list"),
      document.querySelector<HTMLElement>(`.move-list [data-ply="${current}"]`),
    );
  }, [current]);

  // The bar always describes the position on the board (before the move in "best move" view).
  const evaluation: Evaluation | null =
    current === 0
      ? game.start_eval
      : showBest
        ? (analysis?.eval_before ?? null)
        : (analysis?.eval_after ?? null);

  // --- board -----------------------------------------------------------------------

  const explorerFen = explorer ? explorer.fens[explorer.fens.length - 1]! : null;
  const boardFen = explorerFen ?? (showBest && move ? move.fen_before : (move?.fen_after ?? game.start_fen));

  const arrows: Arrow[] = useMemo(() => {
    if (explorer || !showBest || !move || !analysis) return [];
    const result: Arrow[] = [];
    const played = uciSquares(move.uci);
    const best = uciSquares(analysis.best_move_uci);
    if (played) result.push({ startSquare: played[0], endSquare: played[1], color: PLAYED_ARROW });
    if (best && analysis.best_move_uci !== move.uci) {
      result.push({ startSquare: best[0], endSquare: best[1], color: BEST_ARROW });
    }
    return result;
  }, [explorer, showBest, move, analysis]);

  const squareStyles = useMemo(() => {
    if (explorer || showBest || !move) return {};
    const squares = uciSquares(move.uci);
    return squares ? { [squares[0]]: LAST_MOVE, [squares[1]]: LAST_MOVE } : {};
  }, [explorer, showBest, move]);

  // --- explorer ------------------------------------------------------------------------

  const engineGameId = analyzed ? game.id : undefined;

  const startExplorer = () => {
    requestRef.current += 1;
    setExplorer({
      fens: [boardFen],
      sans: [],
      moveEval: null,
      positionEval: null,
      loading: false,
      error: null,
    });
  };

  const onPieceDrop = ({
    sourceSquare,
    targetSquare,
    piece,
  }: {
    sourceSquare: string;
    targetSquare: string | null;
    piece: { pieceType: string };
  }): boolean => {
    if (!explorer || !explorerFen || !targetSquare || !status?.stockfish) return false;
    const chess = new Chess(explorerFen);
    const promotes = piece.pieceType[1] === "P" && /[18]$/.test(targetSquare);
    let played;
    try {
      played = chess.move({ from: sourceSquare, to: targetSquare, promotion: promotes ? "q" : undefined });
    } catch {
      return false; // illegal: the piece goes back
    }
    const request = ++requestRef.current;
    setExplorer({
      ...explorer,
      fens: [...explorer.fens, chess.fen()],
      sans: [...explorer.sans, played.san],
      moveEval: null,
      positionEval: null,
      loading: true,
      error: null,
    });
    api
      .evaluateMove(explorerFen, played.lan, engineGameId)
      .then((result) => {
        if (requestRef.current === request) {
          setExplorer((s) => (s ? { ...s, moveEval: result, loading: false } : s));
        }
      })
      .catch((err: unknown) => {
        if (requestRef.current === request) {
          setExplorer((s) => (s ? { ...s, loading: false, error: messageOf(err) } : s));
        }
      });
    return true;
  };

  const undoExplorer = () => {
    if (!explorer || explorer.sans.length === 0) return;
    requestRef.current += 1;
    setExplorer({
      ...explorer,
      fens: explorer.fens.slice(0, -1),
      sans: explorer.sans.slice(0, -1),
      moveEval: null,
      positionEval: null,
      loading: false,
      error: null,
    });
  };

  const evaluateExplorerPosition = () => {
    if (!explorer || !explorerFen) return;
    const request = ++requestRef.current;
    setExplorer({ ...explorer, loading: true, error: null, positionEval: null });
    api
      .evaluate(explorerFen, engineGameId)
      .then((result) => {
        if (requestRef.current === request) {
          setExplorer((s) => (s ? { ...s, positionEval: result, loading: false } : s));
        }
      })
      .catch((err: unknown) => {
        if (requestRef.current === request) {
          setExplorer((s) => (s ? { ...s, loading: false, error: messageOf(err) } : s));
        }
      });
  };

  const sideToMove = (explorerFen ?? boardFen).split(" ")[1] === "b" ? "b" : "w";

  // --- analysis job ----------------------------------------------------------------------

  const analyse = async () => {
    setJobError(null);
    try {
      setJob(await api.startAnalysis({ game_id: game.id }));
    } catch (err) {
      setJobError(messageOf(err));
    }
  };

  const critical = moves.filter((m) => m.by_user && m.analysis && m.analysis.classification !== "ok");

  return (
    <div className="game-page">
      <GameHeader game={game} />

      {!analyzed && (
        <div className="analyse-banner">
          {job ? (
            <JobProgress
              job={job}
              onFinish={(finished) => {
                if (finished.status === "done") {
                  reload();
                  reloadStatus();
                }
              }}
            />
          ) : (
            <Alert kind="info">
              Esta partida no está analizada.{" "}
              {status?.stockfish ? (
                <button type="button" className="button button-small" onClick={analyse}>
                  Analizar con Stockfish
                </button>
              ) : (
                "Configura Stockfish para analizarla."
              )}
            </Alert>
          )}
          {jobError && <Alert kind="error">{jobError}</Alert>}
        </div>
      )}

      <div className="game-layout">
        <div className="board-column">
          <div className="board-wrap">
            <EvalBar evaluation={explorer ? null : evaluation} orientation={orientation} />
            <div className="board">
              <Chessboard
                options={{
                  id: "teachess-board",
                  position: boardFen,
                  boardOrientation: orientation,
                  arrows,
                  squareStyles,
                  allowDragging: Boolean(explorer && status?.stockfish),
                  allowDrawingArrows: true,
                  canDragPiece: ({ piece }) => piece.pieceType[0] === sideToMove,
                  onPieceDrop,
                  animationDurationInMs: 180,
                }}
              />
            </div>
          </div>

          {!explorer ? (
            <div className="board-controls">
              <button type="button" className="icon-button" onClick={() => goTo(0)} disabled={current === 0} aria-label="Inicio">
                ⏮
              </button>
              <button type="button" className="icon-button" onClick={() => goTo(current - 1)} disabled={current === 0} aria-label="Jugada anterior">
                ◀
              </button>
              <span className="ply-indicator">
                {move ? `${move.label}${move.san}` : "Inicio"} · {current}/{moves.length}
              </span>
              <button type="button" className="icon-button" onClick={() => goTo(current + 1)} disabled={current === moves.length} aria-label="Jugada siguiente">
                ▶
              </button>
              <button type="button" className="icon-button" onClick={() => goTo(moves.length)} disabled={current === moves.length} aria-label="Final">
                ⏭
              </button>
              <button
                type="button"
                className="icon-button"
                onClick={() => setOrientation((o) => (o === "white" ? "black" : "white"))}
                aria-label="Girar el tablero"
                title="Girar el tablero"
              >
                ⇅
              </button>
              {status?.stockfish && (
                <button type="button" className="button button-small button-secondary" onClick={startExplorer}>
                  Explorar desde aquí
                </button>
              )}
            </div>
          ) : (
            <ExplorerPanel
              explorer={explorer}
              onUndo={undoExplorer}
              onEvaluate={evaluateExplorerPosition}
              onExit={() => setExplorer(null)}
            />
          )}

          <EvalChart start={game.start_eval} moves={moves} current={current} onSelect={(ply) => goTo(ply)} />
        </div>

        <div className="side-column">
          {!explorer && (
            <MoveDetail
              move={move}
              game={game}
              showBest={showBest}
              canShowBest={canShowBest}
              onToggleBest={() => setShowBest((s) => !s)}
            />
          )}

          <section className="card">
            <h2>Jugadas</h2>
            <MoveList moves={moves} current={current} onSelect={(ply) => goTo(ply)} />
          </section>

          {analyzed && (
            <section className="card">
              <h2>Tus momentos críticos</h2>
              {critical.length === 0 ? (
                <p className="muted">Sin imprecisiones ni errores según el motor.</p>
              ) : (
                <ul className="critical-list">
                  {critical.map((m) => (
                    <li key={m.ply}>
                      <button
                        type="button"
                        className={`critical ${m.ply === current ? "critical-current" : ""}`}
                        onClick={() => goTo(m.ply, true)}
                      >
                        <span className="critical-move">
                          {m.label}
                          {m.san}
                        </span>
                        <ClassBadge classification={m.analysis!.classification} />
                        <span className="muted small">−{formatPct(m.analysis!.win_loss)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {status && <CoachPanel gameId={game.id} analyzed={analyzed} coach={status.coach} />}
        </div>
      </div>
    </div>
  );
}

function firstCriticalPly(game: GameDetail): number | null {
  const worst = game.moves
    .filter((m) => m.by_user && m.analysis && m.analysis.classification !== "ok")
    .sort((a, b) => b.analysis!.win_loss - a.analysis!.win_loss)[0];
  return worst ? worst.ply : null;
}

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function GameHeader({ game }: { game: GameDetail }) {
  const userIsWhite = game.user_color === "white";
  return (
    <header className="game-header">
      <div>
        <h1>
          <span className={userIsWhite ? "me" : ""}>{game.white}</span>
          <span className="muted"> vs </span>
          <span className={userIsWhite ? "" : "me"}>{game.black}</span>
        </h1>
        <p className="muted">
          {formatDate(game.played_at)} · {formatTimeControl(game.time_control)} ·{" "}
          {PLATFORM_LABELS[game.platform]}
          {game.opening ? ` · ${game.opening}` : ""}
          {game.url && (
            <>
              {" · "}
              <a href={game.url} target="_blank" rel="noreferrer">
                ver original
              </a>
            </>
          )}
        </p>
      </div>
      <div className="game-header-stats">
        <ResultBadge result={game.user_result} />
        {game.summary && (
          <>
            <ErrorCountBadges counts={game.summary.counts} />
            <span className="muted small" title="Pérdida media por jugada en centipeones">
              ACPL {formatAcpl(game.summary.acpl)}
            </span>
          </>
        )}
      </div>
    </header>
  );
}

function MoveDetail({
  move,
  game,
  showBest,
  canShowBest,
  onToggleBest,
}: {
  move: GameMove | undefined;
  game: GameDetail;
  showBest: boolean;
  canShowBest: boolean;
  onToggleBest: () => void;
}) {
  if (!move) {
    return (
      <section className="card move-detail">
        <h2>Posición inicial</h2>
        <p className="muted">
          Usa las flechas del teclado o haz clic en una jugada. Los momentos críticos te llevan a
          tus errores con la mejor jugada marcada.
        </p>
        {game.start_eval && <p>Evaluación: {game.start_eval.text}</p>}
      </section>
    );
  }
  const a = move.analysis;
  return (
    <section className="card move-detail">
      <h2>
        {move.label}
        {move.san} {a && <ClassBadge classification={a.classification} />}
      </h2>
      <p className="muted small">
        {move.by_user ? "Tu jugada" : "Jugada del rival"}
        {a ? ` · ${PHASE_LABELS[a.phase]}` : ""}
        {move.clock_seconds !== null ? ` · reloj ${formatClock(move.clock_seconds)}` : ""}
      </p>
      {a ? (
        <>
          <dl className="facts">
            <dt>Evaluación</dt>
            <dd>
              {a.eval_before.text} → <strong>{a.eval_after.text}</strong>
            </dd>
            <dt>Pérdida</dt>
            <dd>
              {a.win_loss > 0 ? `${formatPct(a.win_loss)} de probabilidad de ganar` : "ninguna"}
              {a.cp_loss > 0 && <span className="muted small"> ({a.cp_loss} cp)</span>}
            </dd>
            <dt>Mejor jugada</dt>
            <dd>
              {a.best_move_san ?? "—"}
              {a.best_move_san === move.san && <span className="muted small"> (la jugaste)</span>}
            </dd>
            {a.engine_line && (
              <>
                <dt>Línea del motor</dt>
                <dd className="mono">{a.engine_line}</dd>
              </>
            )}
          </dl>
          {canShowBest && (
            <button type="button" className="button button-small button-secondary" onClick={onToggleBest}>
              {showBest ? "Ver la posición tras la jugada" : "Ver la mejor jugada en el tablero"}
            </button>
          )}
          {showBest && canShowBest && (
            <p className="muted small arrow-legend">
              <span className="swatch swatch-played" /> jugada · <span className="swatch swatch-best" /> mejor (
              {CLASS_LABELS[a.classification]})
            </p>
          )}
        </>
      ) : (
        <p className="muted">Sin análisis del motor.</p>
      )}
    </section>
  );
}

function ExplorerPanel({
  explorer,
  onUndo,
  onEvaluate,
  onExit,
}: {
  explorer: ExplorerState;
  onUndo: () => void;
  onEvaluate: () => void;
  onExit: () => void;
}) {
  const m = explorer.moveEval;
  const p = explorer.positionEval;
  return (
    <section className="card explorer">
      <div className="explorer-header">
        <h2>Explorador</h2>
        <div className="toolbar">
          <button type="button" className="button button-small button-secondary" onClick={onUndo} disabled={explorer.sans.length === 0}>
            Deshacer
          </button>
          <button type="button" className="button button-small button-secondary" onClick={onEvaluate} disabled={explorer.loading}>
            Evaluar posición
          </button>
          <button type="button" className="button button-small" onClick={onExit}>
            Volver a la partida
          </button>
        </div>
      </div>
      <p className="muted small">
        Mueve las piezas para probar ideas; Stockfish evalúa cada jugada. Los peones coronan en
        dama.
      </p>
      {explorer.sans.length > 0 && <p className="mono">{explorer.sans.join(" ")}</p>}
      {explorer.loading && <p className="muted">Stockfish está pensando…</p>}
      {explorer.error && <Alert kind="error">{explorer.error}</Alert>}
      {m && (
        <p>
          <strong>{m.move}</strong> <ClassBadge classification={m.classification} />{" "}
          {m.is_best ? (
            "es la mejor jugada."
          ) : (
            <>
              Mejor era <strong>{m.best_move ?? "—"}</strong>
              {m.win_loss_pct > 0 && <> (pierdes {formatPct(m.win_loss_pct)})</>}.
            </>
          )}{" "}
          Evaluación: {m.eval_before} → <strong>{m.eval_after}</strong>
          {m.best_reply_line && (
            <>
              <br />
              <span className="muted small">Respuesta del motor: </span>
              <span className="mono">{m.best_reply_line}</span>
            </>
          )}
        </p>
      )}
      {p && (
        <p>
          {p.game_over ? (
            <>Partida terminada: {p.result}</>
          ) : (
            <>
              Evaluación <strong>{p.eval}</strong>
              {p.white_win_pct !== undefined && <> · blancas {formatPct(p.white_win_pct)}</>}
              {p.best_move && (
                <>
                  {" "}
                  · mejor <strong>{p.best_move}</strong>
                </>
              )}
              {p.engine_line && (
                <>
                  <br />
                  <span className="mono">{p.engine_line}</span>
                </>
              )}
            </>
          )}
        </p>
      )}
    </section>
  );
}
