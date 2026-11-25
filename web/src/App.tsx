import { NavLink, Route, Routes } from "react-router-dom";

import { Alert } from "./components/common";
import { GamePage } from "./pages/GamePage";
import { GamesPage } from "./pages/GamesPage";
import { ImportPage } from "./pages/ImportPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ReportPage } from "./pages/ReportPage";
import { useStatus } from "./status";

export function App() {
  const { status, error } = useStatus();
  return (
    <div className="app">
      <header className="header">
        <NavLink to="/" className="brand" aria-label="Teachess, inicio">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          Teachess
        </NavLink>
        <nav className="nav" aria-label="Principal">
          <NavLink to="/" end>
            Partidas
          </NavLink>
          <NavLink to="/report">Informe</NavLink>
          <NavLink to="/import">Importar</NavLink>
        </nav>
        {status && (
          <span
            className={`pill ${status.stockfish ? "pill-ok" : "pill-warn"}`}
            title={
              status.stockfish
                ? `Stockfish listo (profundidad ${status.engine_depth})`
                : "Configura STOCKFISH_PATH en .env para analizar"
            }
          >
            {status.stockfish ? "Stockfish listo" : "Sin Stockfish"}
          </span>
        )}
      </header>
      <main className="main">
        {error && (
          <Alert kind="error">
            No se pudo conectar con Teachess: {error}. Arranca el servidor con{" "}
            <code>uv run teachess serve</code>.
          </Alert>
        )}
        {status && !status.stockfish && (
          <Alert kind="warning">
            Stockfish no está configurado: puedes importar y ver partidas, pero no analizarlas.
            Indica la ruta del binario en <code>STOCKFISH_PATH</code> (archivo <code>.env</code>)
            y reinicia Teachess.
          </Alert>
        )}
        <Routes>
          <Route path="/" element={<GamesPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/games/:id" element={<GamePage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/report/:user" element={<ReportPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      <footer className="footer muted small">
        Teachess {status?.version ?? ""} · El motor calcula, el coach explica · Tus datos se
        quedan en este equipo.
      </footer>
    </div>
  );
}
