# Próximos pasos

Última actualización: 2026-10-28.

## Dónde estamos

- La **Fase 1 está implementada** en la rama `phase-1-pipeline` (todavía no fusionada en `main`).
- Hay 39 tests y pasan, igual que `ruff` y `mypy`.
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
- [ ] Clasificar errores por probabilidad de victoria (plan acordado el 2026-10-28, ver abajo).
- [ ] Fusionar `phase-1-pipeline` en `main`.

### Plan: clasificación por probabilidad de victoria

Motivo: con centipeones el informe es mucho más estricto que Chess.com (marca como error jugadas que solo son imperfectas, sobre todo en posiciones ya ganadas o perdidas). Simulación sobre 10 partidas reales: errores graves 19 → 7, errores 56 → 9, imprecisiones 33 → 27.

1. `engine/analysis.py`: `win_percent()` con la fórmula de Lichess (`50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)`, mate = 0/100 %). Clasificar por caída de % de victoria: imprecisión ≥ 10, error ≥ 20, error grave ≥ 30. Mantener `cp_loss` para el ACPL.
2. Esquema: nueva columna `win_loss` en `move_analysis` y subir `PRAGMA user_version`.
3. `report/`: columna «Pérdida %» en el informe por partida.
4. Tests: casos de posición ya ganada y de mate permitido.
5. Actualizar las decisiones de la Fase 1 en `CLAUDE.md`, y después ejecutar `analyze --reanalyze` (las evaluaciones ya están en caché).

Opcional, propuesto y sin decidir: mostrar en el informe la profundidad de la refutación de cada error (principio «Juzgar con criterio humano» de `CLAUDE.md`).

## 3. Fase 2: coach conversacional sobre una partida

Pedir a Claude que prepare el plan de la Fase 2 (ver `CLAUDE.md`). Se apoyará en lo que ya existe:
- `get_game` y `get_critical_moments` leen las tablas `games` y `move_analysis` (`db/repository.py`).
- `evaluate_position` usa `StockfishEngine` + `PersistentCacheEngine` (`engine/`).

## Mejoras abiertas (sin decidir)

- **Recorte de ±1000 cp**: en posiciones ya perdidas, permitir un mate cuenta poco. Lo resuelve el plan de probabilidad de victoria.
- **Heurística de fase**: es simple (apertura hasta la jugada 10, final por material). Afinarla si los recuentos por fase no cuadran con la intuición.
