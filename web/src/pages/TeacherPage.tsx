import { useEffect, useMemo, useState } from "react";
import { Chessboard, type Arrow } from "react-chessboard";
import { Link } from "react-router-dom";

import { api } from "../api";
import { Alert, Loading } from "../components/common";
import { TeacherTerminal, type TerminalState } from "../components/TeacherTerminal";
import { uciSquares } from "../format";
import { useAsync } from "../hooks";
import { useStatus } from "../status";
import type { TeacherBoard } from "../types";

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
            <TeacherTerminal token={teacher.token} session={session} onState={setState} />
          </div>
          <aside className="teacher-side">
            <BoardPanel />
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

/** The last position the teacher showed with `show_position`, straight from the tool. */
function BoardPanel() {
  const [board, setBoard] = useState<TeacherBoard | null>(null);
  const { status } = useStatus();

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .teacherBoard()
        .then((next) => {
          if (!cancelled) setBoard((prev) => (prev?.updated_at === next?.updated_at ? prev : next));
        })
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, BOARD_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const arrows: Arrow[] = useMemo(() => {
    const squares = uciSquares(board?.arrow?.uci);
    return squares ? [{ startSquare: squares[0], endSquare: squares[1], color: ARROW_COLOR }] : [];
  }, [board]);

  return (
    <div className="card">
      <h2>Tablero de la clase</h2>
      <div className="board">
        <Chessboard
          options={{
            id: "teacher-board",
            position: board?.fen ?? START_FEN,
            boardOrientation: board?.orientation ?? "white",
            arrows,
            allowDragging: false,
            allowDrawingArrows: true,
            animationDurationInMs: 200,
          }}
        />
      </div>
      <p className="board-caption">
        {board
          ? `${board.caption || "Posición de la clase"}${board.arrow ? ` · flecha: ${board.arrow.san}` : ""}`
          : "Aquí aparecerán las posiciones que te enseñe el profesor."}
      </p>
      {board && (
        <p className="muted small">
          Juegan {board.fen.split(" ")[1] === "w" ? "blancas" : "negras"}
          {status?.stockfish ? "" : " · Stockfish no está configurado"}
        </p>
      )}
    </div>
  );
}
