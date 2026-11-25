# Próximos pasos

Última actualización: 2026-11-25 (Fase 2).

## Dónde estamos

- La **Fase 1 está implementada** en la rama `phase-1-pipeline`, con el PR #1 abierto hacia `main`.
- La **Fase 2 (coach) está implementada** en la rama `phase-2-coach` (PR #2). Se usa gratis desde Claude Code mediante un servidor MCP (sección 3).
- Hay 83 tests y pasan, igual que `ruff` y `mypy`.
- **Clasificación por probabilidad de victoria implementada** (2026-11-25). La base local se migró a la versión 2 del esquema: con tus 10 partidas, errores graves 19 → 7, errores 56 → 9, imprecisiones 33 → 27 (igual que la simulación). Un `analyze --reanalyze --depth 14` desde caché da exactamente lo mismo que la migración.
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
- [x] Comparado con Chess.com en la partida #6 (2026-11-25), ver abajo.
- [ ] Fusionar `phase-1-pipeline` en `main`: PR abierto, https://github.com/Ahgolderos12/teachess/pull/1.

### Comparación con Chess.com (partida #6)

| Jugada | Chess.com | Teachess | Pérdida % |
|---|---|---|---|
| 7 | imprecisión | imprecisión | 12,4 |
| 10 | error | imprecisión | 15,9 |
| 11 | error grave | error grave | 46,9 |
| 12 | imprecisión | — | 7,9 |
| 13 | error | imprecisión | 12,7 |
| 15 | error | — | 8,4 |
| 23 | error grave | imprecisión | 16,9 |
| 27 | imprecisión | — | 4,1 |
| 29 | imprecisión | — | 5,6 |
| 40 | imprecisión | imprecisión | 10,2 |
| 43 | error | error | 20,3 |
| 53 | oportunidad perdida | error grave | 33,9 |
| 68 | error grave | error grave | 43,2 |

- Todo lo que marca Teachess lo marca también Chess.com (ningún falso positivo), y los errores decisivos (11, 53, 68) coinciden.
- Teachess es más indulgente: no marca 4 jugadas pequeñas (4-8 %) en posiciones ya perdidas (−3,4 a −5), y baja un nivel 10, 13 y 23.
- Chess.com usa umbrales de «puntos esperados» que equivalen más o menos a la mitad (≈ 5/10/20) y un modelo que depende del rating. Con 5/10/20 en las 10 partidas: graves 16, errores 27, imprecisiones 36. En la partida #6 no mejora el acuerdo (6 de 12 frente a 5 de 12): sube unas jugadas y pasa de largo otras.
- La 23 (−2,7 → −5,9) es la mayor discrepancia: probablemente es la evaluación de Chess.com, no el umbral.
- **Sin decidir**: mantener 10/20/30 (más humano y coherente con el principio de no castigar posiciones decididas) o bajar a 5/10/20 (más parecido a Chess.com). Es un cambio de tres constantes en `engine/scoring.py` y una reclasificación sin motor.

Opcional, propuesto y sin decidir: mostrar en el informe la profundidad de la refutación de cada error (principio «Juzgar con criterio humano» de `CLAUDE.md`).

## 3. Fase 2: coach conversacional sobre una partida

**Implementada en la rama `phase-2-coach`** (PR #2, apilado sobre el #1). 83 tests (sin llamadas a la API), `ruff` y `mypy` sin errores. Plan, decisiones y coste estimado en `docs/PHASE_2_PLAN.md`.

Dos vías:
- **Claude Code + servidor MCP (coste 0, la elegida)**: probada de punta a punta con el cliente MCP oficial, tu base de datos y Stockfish real. Falta probarla dentro de Claude Code: abrir Claude Code en esta carpeta, aprobar el servidor `teachess` y escribir `/mcp__teachess__coach 6`.
- **`teachess coach` por API (de pago)**: lista para cuando haya más usuarios; sin probar con la API real (no se gasta sin permiso).

Falta:
- [ ] Primera sesión real con `/mcp__teachess__coach 6` en Claude Code: comprobar que no inventa jugadas, que usa `evaluate_move` en las preguntas «¿y si…?» y que pasa el `game_id`.
- [ ] Ajustar el prompt (`coach/prompts.py`) según esa prueba.
- [ ] Fusionar el PR #1 y después el #2.

## Mejoras abiertas (sin decidir)

- **Heurística de fase**: es simple (apertura hasta la jugada 10, final por material). Afinarla si los recuentos por fase no cuadran con la intuición.
