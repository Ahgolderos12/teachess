# Teachess

Entrenador personal de ajedrez con IA que aprende del jugador: analiza sus partidas con Stockfish y, en fases posteriores, recuerda cómo juega y cómo piensa para ofrecer un aprendizaje personalizado.

Estado: Fase 1 (importar y analizar), Fase 2 (coach con Claude), **aplicación web** y **Teacher** (profesor que abre la clase solo a partir de tus estadísticas) implementados. Ver `CLAUDE.md` para la visión y las fases.

## Puesta en marcha

Requiere [uv](https://docs.astral.sh/uv/).

```
uv sync
copy .env.example .env   # y rellenar valores
uv run teachess --help
```

## Aplicación web

Requiere además [Node.js](https://nodejs.org/) para compilar la web (solo la primera vez y tras cambiarla).

```
cd web && npm install && npm run build && cd ..
uv run teachess serve
```

Se abre en `http://127.0.0.1:8000`:

- **Teacher**: tu profesor. Es Claude Code con tu suscripción (no gasta créditos de la API), en una terminal dentro de la web, con un tablero al lado. Estudia tus últimas partidas y empieza la clase por lo que más te conviene trabajar. Requiere tener [Claude Code](https://claude.com/claude-code) instalado y con sesión iniciada; solo en macOS y Linux.
- **Partidas**: cada partida en el tablero (errores, mejor jugada, gráfica de evaluación, explorador para probar jugadas).
- **Estadísticas**: resultados, ELO, aperturas, errores, tiempo, conversión… y lo que ve el profesor.
- **Importar**. Además, mientras la web está abierta, tus partidas nuevas de Chess.com/Lichess se importan y analizan solas al arrancar y cada 6 h (`TEACHESS_SYNC_HOURS`).

Sin la web, la misma clase se da desde Claude Code en esta carpeta: `/mcp__teachess__teacher` (o `/mcp__teachess__coach <id>` para una partida concreta). El chat por partida dentro de la web usa la API de pago de Anthropic y solo se activa si pones `ANTHROPIC_API_KEY` en `.env`.

## Uso desde la terminal

```
# 1. Importar partidas (usa CHESSCOM_USER / LICHESS_USER si no pasas --user)
uv run teachess import --platform lichess --max-games 20
uv run teachess import --platform chesscom --user <usuario>
uv run teachess import --platform pgn --file partidas.pgn --user <tu nombre en el PGN>

# 2. Analizar con Stockfish (solo las partidas pendientes; requiere STOCKFISH_PATH)
uv run teachess analyze --user <usuario> --depth 14

# 3. Ver el informe de errores
uv run teachess report --user <usuario>
uv run teachess report --game <id>
```

## Desarrollo

```
uv run pytest
uv run ruff check .
uv run mypy src
cd web && npm test && npm run typecheck   # frontend
cd web && npm run dev                     # web en modo desarrollo (con `teachess serve` en marcha)
```
