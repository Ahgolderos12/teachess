# Próximos pasos

Última actualización: 2026-10-28.

## Dónde estamos

- La **Fase 1 está implementada** en la rama `phase-1-pipeline` (todavía no fusionada en `main`).
- Hay 39 tests y pasan, igual que `ruff` y `mypy`.
- Probado de punta a punta con Stockfish real usando un archivo PGN local.
- **Pendiente de probar con datos reales**: la importación desde Chess.com y Lichess. Desde el equipo de trabajo no había conexión con esas APIs (error SSL de la red corporativa), así que hoy solo está probada con respuestas simuladas.

## Puesta en marcha en otro equipo

```
git clone https://github.com/Ahgolderos12/teachess.git
cd teachess
git checkout phase-1-pipeline
uv sync
copy .env.example .env
```

Después, rellenar en `.env` al menos `STOCKFISH_PATH` (ruta al binario de Stockfish) y `CHESSCOM_USER`. El `.env` y la base de datos `data/teachess.sqlite` no están en git, así que no viajan entre equipos: en un equipo nuevo hay que volver a crear el `.env` y a importar las partidas.

## 1. Probar con mis partidas reales de Chess.com

```
uv run teachess import --platform chesscom --max-games 10
uv run teachess analyze --user <usuario> --depth 14
uv run teachess report --user <usuario>
uv run teachess report --game <id>
```

- Si las tildes se ven mal en Git Bash: `export PYTHONIOENCODING=utf-8`, o usar PowerShell.

Comprobar:
- Que color, rival, resultado y fecha de cada partida sean correctos.
- Que los errores graves tengan sentido comparados con el análisis de Chess.com o Lichess. Los umbrales son distintos, pero los errores grandes deben coincidir.
- Que reimportar no duplique partidas (debe mostrar `ya importadas: N`).
- Si falla el parseo de la respuesta de Chess.com (por ejemplo, un `KeyError`), revisar `src/teachess/ingest/chesscom.py`: es la parte menos probada.

## 2. Cerrar la Fase 1

- [ ] Prueba real con Chess.com correcta (y, opcionalmente, con Lichess).
- [ ] Fusionar `phase-1-pipeline` en `main`.
- [ ] Decidir si se mejora la clasificación de errores (ver «Mejoras abiertas»).

## 3. Fase 2: coach conversacional sobre una partida

Pedir a Claude que prepare el plan de la Fase 2 (ver `CLAUDE.md`). Se apoyará en lo que ya existe:
- `get_game` y `get_critical_moments` leen las tablas `games` y `move_analysis` (`db/repository.py`).
- `evaluate_position` usa `StockfishEngine` + `PersistentCacheEngine` (`engine/`).

## Mejoras abiertas (sin decidir)

- **Recorte de ±1000 cp**: en posiciones ya perdidas, permitir un mate cuenta poco. Por ejemplo, una jugada que permite mate en 1 desde −8.75 sale solo como «error» (pérdida 125). Alternativa: clasificar por probabilidad de victoria, como Lichess.
- **Heurística de fase**: es simple (apertura hasta la jugada 10, final por material). Afinarla si los recuentos por fase no cuadran con la intuición.
