# Próximos pasos

Última actualización: 2026-11-25.

## Dónde estamos

- La **Fase 1 está implementada** en la rama `phase-1-pipeline` (todavía no fusionada en `main`).
- Hay 44 tests y pasan, igual que `ruff` y `mypy`.
- **Clasificación por probabilidad de victoria implementada** (2026-11-25, cambios sin commitear). La base local se migró a la versión 2 del esquema: con tus 10 partidas, errores graves 19 → 7, errores 56 → 9, imprecisiones 33 → 27 (igual que la simulación). Un `analyze --reanalyze --depth 14` desde caché da exactamente lo mismo que la migración.
- Probado de punta a punta con Stockfish real usando un archivo PGN local.
- **Chess.com probado con datos reales** (2026-10-28, Mac personal, usuario `ahgolderos`): 10 partidas importadas, reimportar no duplica, color/rival/resultado coinciden con la API, análisis a profundidad 14 en ~1 min. Falta comparar los errores graves con el análisis de Chess.com.
- **Lichess sigue sin probar con datos reales.** Desde el equipo de trabajo no había conexión con las APIs (error SSL de la red corporativa).

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

- [x] Prueba real con Chess.com correcta (falta Lichess, opcional).
- [x] Clasificar errores por probabilidad de victoria (`engine/scoring.py`, esquema v2 con `win_loss`, columnas «Pérdida %» y «Pérdida cp» en el informe por partida).
- [ ] Revisar a ojo el informe de alguna partida (`report --game 6`, por ejemplo) y compararlo con Chess.com.
- [ ] Fusionar `phase-1-pipeline` en `main`.

Opcional, propuesto y sin decidir: mostrar en el informe la profundidad de la refutación de cada error (principio «Juzgar con criterio humano» de `CLAUDE.md`).

## 3. Fase 2: coach conversacional sobre una partida

Pedir a Claude que prepare el plan de la Fase 2 (ver `CLAUDE.md`). Se apoyará en lo que ya existe:
- `get_game` y `get_critical_moments` leen las tablas `games` y `move_analysis` (`db/repository.py`).
- `evaluate_position` usa `StockfishEngine` + `PersistentCacheEngine` (`engine/`).

## Mejoras abiertas (sin decidir)

- **Heurística de fase**: es simple (apertura hasta la jugada 10, final por material). Afinarla si los recuentos por fase no cuadran con la intuición.
