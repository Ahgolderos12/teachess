import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { Alert, JobProgress } from "../components/common";
import { PLATFORM_LABELS } from "../format";
import { useStatus } from "../status";
import type { Color, ImportResult, Job, Platform } from "../types";

const PLATFORMS: Platform[] = ["chesscom", "lichess", "pgn"];
const MAX_PGN_BYTES = 5_000_000;

export function ImportPage() {
  const { status, reload: reloadStatus } = useStatus();
  const [platform, setPlatform] = useState<Platform>("chesscom");
  const [user, setUser] = useState("");
  const [maxGames, setMaxGames] = useState(20);
  const [pgn, setPgn] = useState("");
  const [color, setColor] = useState<Color | "">("");
  const [analyze, setAnalyze] = useState(true);
  const [job, setJob] = useState<Job<ImportResult> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const defaultUser = platform === "pgn" ? "" : (status?.default_users[platform] ?? "");
  useEffect(() => setUser(defaultUser ?? ""), [defaultUser]);
  useEffect(() => {
    if (status && !status.stockfish) setAnalyze(false);
  }, [status]);

  const running = job !== null && (job.status === "queued" || job.status === "running");

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_PGN_BYTES) {
      setError("El archivo es demasiado grande (máximo 5 MB).");
      return;
    }
    setError(null);
    setPgn(await file.text());
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      setJob(
        await api.startImport({
          platform,
          user: user.trim() || undefined,
          max_games: maxGames,
          pgn: platform === "pgn" ? pgn : undefined,
          color: platform === "pgn" && color ? color : null,
          analyze,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="narrow">
      <h1>Importar partidas</h1>
      <div className="tabs" role="tablist" aria-label="Origen">
        {PLATFORMS.map((p) => (
          <button
            key={p}
            type="button"
            role="tab"
            aria-selected={platform === p}
            className={`tab ${platform === p ? "tab-active" : ""}`}
            onClick={() => setPlatform(p)}
            disabled={running}
          >
            {p === "pgn" ? "Archivo PGN" : PLATFORM_LABELS[p]}
          </button>
        ))}
      </div>

      <form className="card form" onSubmit={submit}>
        <label className="field">
          {platform === "pgn" ? "Tu nombre en las partidas" : `Tu usuario de ${PLATFORM_LABELS[platform]}`}
          <input
            value={user}
            onChange={(e) => setUser(e.target.value)}
            placeholder={platform === "pgn" ? "Como aparece en el PGN" : "usuario"}
            required
            maxLength={100}
            autoComplete="off"
          />
        </label>

        {platform === "pgn" ? (
          <>
            <label className="field">
              Archivo PGN
              <input type="file" accept=".pgn,text/plain" onChange={(e) => readFile(e.target.files?.[0])} />
            </label>
            <label className="field">
              …o pega aquí las partidas
              <textarea
                value={pgn}
                onChange={(e) => setPgn(e.target.value)}
                rows={8}
                placeholder={'[White "Yo"]\n[Black "Rival"]\n\n1. e4 e5 2. Nf3 …'}
                spellCheck={false}
              />
            </label>
            <label className="field">
              Tu color (si tu nombre no aparece en el PGN)
              <select value={color} onChange={(e) => setColor(e.target.value as Color | "")}>
                <option value="">Detectar por el nombre</option>
                <option value="white">Blancas</option>
                <option value="black">Negras</option>
              </select>
            </label>
          </>
        ) : (
          <label className="field">
            Máximo de partidas (las más recientes)
            <input
              type="number"
              min={1}
              max={500}
              value={maxGames}
              onChange={(e) => setMaxGames(Math.min(500, Math.max(1, Number(e.target.value) || 1)))}
            />
          </label>
        )}

        <label className="checkbox">
          <input
            type="checkbox"
            checked={analyze}
            onChange={(e) => setAnalyze(e.target.checked)}
            disabled={!status?.stockfish}
          />
          Analizar con Stockfish al terminar
          {status?.stockfish ? (
            <span className="muted small"> (≈ 5-10 s por partida)</span>
          ) : (
            <span className="muted small"> (Stockfish no está configurado)</span>
          )}
        </label>

        <button
          type="submit"
          className="button"
          disabled={submitting || running || (platform === "pgn" && !pgn.trim())}
        >
          {running ? "Importando…" : "Importar"}
        </button>
      </form>

      {error && <Alert kind="error">{error}</Alert>}
      {job && (
        <JobProgress
          job={job}
          onFinish={() => reloadStatus()}
          renderResult={(result) => <ImportSummary result={result} />}
        />
      )}
    </section>
  );
}

function ImportSummary({ result }: { result: ImportResult }) {
  return (
    <Alert kind={result.new || result.existing ? "success" : "warning"}>
      <p>
        <strong>{result.new}</strong> partida(s) nueva(s), {result.existing} ya importada(s),{" "}
        {result.skipped} descartada(s) (variantes, partidas inválidas o en las que no jugabas).
      </p>
      {result.analysis && <p>Analizadas: {result.analysis.analyzed} (profundidad {result.analysis.depth}).</p>}
      {result.analysis_error && <p>No se pudieron analizar: {result.analysis_error}</p>}
      <p>
        <Link to={`/?user=${encodeURIComponent(result.username)}`}>Ver las partidas</Link>
        {" · "}
        <Link to={`/report/${encodeURIComponent(result.username)}`}>Ver el informe</Link>
      </p>
    </Alert>
  );
}
