import { Chess } from "chess.js";
import { type MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import { Chessboard, type Arrow } from "react-chessboard";
import { Link } from "react-router-dom";

import { api } from "../api";
import { Alert, Loading } from "../components/common";
import {
  TeacherTerminal,
  type TerminalSender,
  type TerminalState,
} from "../components/TeacherTerminal";
import { CLASS_LABELS, formatNumber, lineText, sideToMove, uciSquares } from "../format";
import { useAsync } from "../hooks";
import { useStatus } from "../status";
import type { MoveEvaluation, TeacherBoard } from "../types";

const BOARD_POLL_MS = 1_500;
const ARROW_COLOR = "rgba(31, 111, 92, 0.85)";
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

const STATE_LABELS: Record<TerminalState, string> = {
  connecting: "Conectando con Claude Code…",
  open: "Clase en curso",
  ended: "Clase terminada",
  error: "No se pudo abrir la terminal",
};

export function TeacherPage() {
  const info = useAsync(() => api.teacher(), []);
  const [session, setSession] = useState(0);
  const [state, setState] = useState<TerminalState>("connecting");
  const sender = useRef<TerminalSender | null>(null);

  if (info.error) return <Alert kind="error">{info.error}</Alert>;
  if (!info.data) return <Loading />;
  const teacher = info.data;

  return (
    <section className="teacher-page">
      <div className="page-header">
        <h1>Teacher</h1>
        {teacher.available && (
          <div className="toolbar">
            <span className={`pill ${state === "open" ? "pill-ok" : state === "error" ? "pill-warn" : "pill-muted"}`}>
              {STATE_LABELS[state]}
            </span>
            <button type="button" className="button button-secondary" onClick={() => setSession((s) => s + 1)}>
              Nueva clase
            </button>
          </div>
        )}
      </div>
      {!teacher.available || !teacher.token ? (
        <Unavailable reason={teacher.reason} command={teacher.manual_command} />
      ) : (
        <div className="teacher-layout">
          <div className="card terminal-card">
            <TeacherTerminal
              token={teacher.token}
              session={session}
              onState={setState}
              senderRef={sender}
            />
          </div>
          <aside className="teacher-side">
            <BoardPanel sender={sender} canSend={state === "open"} />
            <p className="muted small">
              Tu profesor es Claude Code con tu suscripción: no gasta créditos de la API. Solo puede
              usar las herramientas de Teachess (tus partidas y Stockfish), no tus archivos ni tu
              navegador. Las cifras salen del diagnóstico de tus partidas; las tienes también en{" "}
              <Link to="/stats">Estadísticas</Link>.
            </p>
          </aside>
        </div>
      )}
    </section>
  );
}

function Unavailable({ reason, command }: { reason: string | null; command: string }) {
  return (
    <div className="card narrow">
      <Alert kind="warning">{reason ?? "La terminal integrada no está disponible."}</Alert>
      <p>Puedes dar la misma clase desde cualquier terminal, en la carpeta de Teachess:</p>
      <pre className="code-block">{command}</pre>
      <p className="muted small">
        Claude Code carga el servidor de Teachess desde <code>.mcp.json</code> la primera vez que
        lo apruebas.
      </p>
    </div>
  );
}

type BoardMode = "answer" | "analyze";

interface Line {
  fens: string[]; // positions after each move
  sans: string[];
  evals: (MoveEvaluation | null)[];
}

const EMPTY_LINE: Line = { fens: [], sans: [], evals: [] };

/**
 * The lesson's board: the last position the teacher showed with `show_position` (straight
 * from the tool, never from the model's text). The player can answer by moving a piece, or
 * analyse lines freely with Stockfish without bothering the teacher.
 */
function BoardPanel({ sender, canSend }: { sender: MutableRefObject<TerminalSender | null>; canSend: boolean }) {
  const [board, setBoard] = useState<TeacherBoard | null>(null);
  const [mode, setMode] = useState<BoardMode>("answer");
  const [line, setLine] = useState<Line>(EMPTY_LINE);
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  const shownAt = useRef<string | null>(null);
  const { status } = useStatus();

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .teacherBoard()
        .then((next) => {
          if (cancelled) return;
          if (shownAt.current === (next?.updated_at ?? null)) return;
          shownAt.current = next?.updated_at ?? null;
          setBoard(next);
          setLine(EMPTY_LINE); // a new position from the teacher replaces the local line
          setSent(null);
          setError(null);
        })
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, BOARD_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const baseFen = board?.fen ?? START_FEN;
  const currentFen = line.fens[line.fens.length - 1] ?? baseFen;
  const lastEval = line.evals[line.evals.length - 1] ?? null;
  const answering = mode === "answer";
  const canMove =
    Boolean(board) && (answering ? canSend && line.sans.length === 0 : Boolean(status?.stockfish));

  const arrows: Arrow[] = useMemo(() => {
    if (line.sans.length) return [];
    const squares = uciSquares(board?.arrow?.uci);
    return squares ? [{ startSquare: squares[0], endSquare: squares[1], color: ARROW_COLOR }] : [];
  }, [board, line.sans.length]);

  const reset = () => {
    request.current += 1;
    setLine(EMPTY_LINE);
    setSent(null);
    setError(null);
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
    if (!canMove || !targetSquare) return false;
    const chess = new Chess(currentFen);
    const promotes = piece.pieceType[1] === "P" && /[18]$/.test(targetSquare);
    let played;
    try {
      played = chess.move({ from: sourceSquare, to: targetSquare, promotion: promotes ? "q" : undefined });
    } catch {
      return false; // illegal: the piece goes back
    }
    const index = line.sans.length;
    setLine((l) => ({ fens: [...l.fens, chess.fen()], sans: [...l.sans, played.san], evals: [...l.evals, null] }));
    setError(null);
    if (answering) {
      const message = `Mi jugada en el tablero: ${played.san} (posición: ${currentFen})`;
      if (sender.current?.(message)) setSent(played.san);
      else setError("La terminal no está conectada: escribe la jugada en ella.");
      return true;
    }
    const id = ++request.current;
    api
      .evaluateMove(currentFen, played.lan)
      .then((result) => {
        if (request.current !== id) return;
        setLine((l) => {
          const evals = [...l.evals];
          evals[index] = result;
          return { ...l, evals };
        });
      })
      .catch((err: unknown) => {
        if (request.current === id) setError(err instanceof Error ? err.message : String(err));
      });
    return true;
  };

  const undo = () => {
    request.current += 1;
    setLine((l) => ({ fens: l.fens.slice(0, -1), sans: l.sans.slice(0, -1), evals: l.evals.slice(0, -1) }));
    setError(null);
  };

  return (
    <div className="card">
      <div className="card-header">
        <h2>Tablero de la clase</h2>
        <div className="tabs" role="tablist" aria-label="Modo del tablero">
          {(["answer", "analyze"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              className={`tab tab-small ${mode === m ? "tab-active" : ""}`}
              onClick={() => {
                setMode(m);
                reset();
              }}
            >
              {m === "answer" ? "Responder" : "Analizar"}
            </button>
          ))}
        </div>
      </div>
      <div className="board">
        <Chessboard
          options={{
            id: "teacher-board",
            position: currentFen,
            boardOrientation: board?.orientation ?? "white",
            arrows,
            allowDragging: canMove,
            allowDrawingArrows: true,
            canDragPiece: ({ piece }) => piece.pieceType[0] === sideToMove(currentFen),
            onPieceDrop,
            animationDurationInMs: 200,
          }}
        />
      </div>
      <p className="board-caption">
        {board
          ? `${board.caption || "Posición de la clase"}${board.arrow && !line.sans.length ? ` · flecha: ${board.arrow.san}` : ""}`
          : "Aquí aparecerán las posiciones que te enseñe el profesor."}
      </p>
      {board && (
        <div className="board-help small">
          {answering ? (
            sent ? (
              <p>
                Has respondido <strong>{sent}</strong>; el profesor la está mirando.{" "}
                <button type="button" className="link-button" onClick={reset}>
                  Volver a la posición
                </button>
              </p>
            ) : (
              <p className="muted">
                Juegan {sideToMove(baseFen) === "w" ? "blancas" : "negras"}. Mueve una pieza para
                responder al profesor{canSend ? "" : " (cuando la terminal esté conectada)"}.
              </p>
            )
          ) : (
            <>
              <p className="muted">
                Prueba jugadas de los dos bandos; Stockfish evalúa cada una. El profesor no ve esto.
              </p>
              {line.sans.length > 0 && (
                <>
                  <p className="mono">{lineText(baseFen, line.sans)}</p>
                  {lastEval ? (
                    <p>
                      <strong>{lastEval.move}</strong>: {lastEval.eval_after}
                      {lastEval.is_best
                        ? " · la mejor jugada"
                        : ` · mejor era ${lastEval.best_move ?? "—"}`}
                      {lastEval.classification !== "ok" &&
                        ` · ${CLASS_LABELS[lastEval.classification]} (−${formatNumber(lastEval.win_loss_pct)} %)`}
                    </p>
                  ) : (
                    !error && <p className="muted">Stockfish está pensando…</p>
                  )}
                  <p>
                    <button type="button" className="link-button" onClick={undo}>
                      Deshacer
                    </button>{" "}
                    ·{" "}
                    <button type="button" className="link-button" onClick={reset}>
                      Volver a la posición de la clase
                    </button>
                  </p>
                </>
              )}
              {!status?.stockfish && <p className="muted">Stockfish no está configurado.</p>}
            </>
          )}
          {error && <p className="error-text">{error}</p>}
        </div>
      )}
    </div>
  );
}
