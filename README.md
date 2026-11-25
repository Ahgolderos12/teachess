# Teachess

Entrenador personal de ajedrez con IA que aprende del jugador: analiza sus partidas con Stockfish y, en fases posteriores, recuerda cómo juega y cómo piensa para ofrecer un aprendizaje personalizado.

Estado: Fase 1 (importar y analizar), Fase 2 (coach con Claude) y **aplicación web** implementadas. Ver `CLAUDE.md` para la visión y las fases.

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

Se abre en `http://127.0.0.1:8000`: importar partidas, analizarlas con Stockfish, revisar cada partida en el tablero (errores, mejor jugada, gráfica de evaluación, explorador para probar jugadas) y ver tu informe.

El coach es gratis desde Claude Code (`/mcp__teachess__coach <id>`, con tu suscripción). El chat dentro de la web usa la API de pago de Anthropic y solo se activa si pones `ANTHROPIC_API_KEY` en `.env`.

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
