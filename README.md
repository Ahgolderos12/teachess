# Teachess

Entrenador personal de ajedrez con IA que aprende del jugador: analiza sus partidas con Stockfish y, en fases posteriores, recuerda cómo juega y cómo piensa para ofrecer un aprendizaje personalizado.

Estado: **Fase 1** (MVP sin LLM, CLI). Ver `CLAUDE.md` para la visión y las fases.

## Puesta en marcha

Requiere [uv](https://docs.astral.sh/uv/).

```
uv sync
copy .env.example .env   # y rellenar valores
uv run teachess --help
```

## Desarrollo

```
uv run pytest
uv run ruff check .
uv run mypy src
```
