# Teachess

Entrenador personal de ajedrez con IA que aprende del jugador: analiza sus partidas con Stockfish y, en fases posteriores, recuerda cómo juega y cómo piensa para ofrecer un aprendizaje personalizado.

Estado: **Fase 1 completa** (MVP sin LLM, CLI). Ver `CLAUDE.md` para la visión y las fases.

## Puesta en marcha

Requiere [uv](https://docs.astral.sh/uv/).

```
uv sync
copy .env.example .env   # y rellenar valores
uv run teachess --help
```

## Uso

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
```
