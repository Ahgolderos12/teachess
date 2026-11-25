# Aplicación web de Teachess

Estado: implementada en la rama `phase-5-web` (2026-11-25), a petición del usuario («crea la aplicación / web de Teachess, implementa todo lo que consideres»). Adelanta la API de la Fase 4 y la interfaz de la Fase 5; la memoria (Fase 3) y el plan de entrenamiento (Fase 4) siguen pendientes.

## Arquitectura

- **Un solo proceso local**: `uv run teachess serve` levanta FastAPI (API en `/api`) y sirve la web ya compilada. Se abre en `http://127.0.0.1:8000`. Solo escucha en local por defecto: los datos del jugador no salen del equipo.
- **Backend** (`src/teachess/api/`): FastAPI sobre los mismos módulos que la CLI (`ingest`, `engine`, `db`, `report`, `coach`). Sin lógica de ajedrez nueva.
- **Frontend** (`web/`): React + TypeScript con Vite, `react-chessboard` para el tablero y `chess.js` para mover piezas en el explorador (la validación definitiva la hace `python-chess` en el servidor).
  - Cambio respecto a `CLAUDE.md` (Next.js): la app es local, de un solo usuario y no necesita renderizado en servidor. Una SPA de Vite se compila a archivos estáticos que sirve FastAPI, así que basta un proceso y un comando; Next.js exigiría un segundo servidor o renunciar a rutas dinámicas como `/games/6`.
- **Tareas largas** (importar, analizar): se lanzan en segundo plano y la web consulta su progreso (`/api/jobs/{id}`). Cada tarea abre su propia conexión SQLite y su propio Stockfish.

## Coste 0

- Todo lo que hace la web es gratis: importar, analizar, informes, tablero, explorador con Stockfish.
- El chat del coach en la web necesita la API de Anthropic (de pago, ~0,25 $ por sesión con Opus). **Solo se activa si hay `ANTHROPIC_API_KEY` en `.env`**; si no, el panel del coach explica cómo usarlo gratis desde Claude Code (`/mcp__teachess__coach <id>`), con un botón para copiar el comando.

## API

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/api/status` | Estado: Stockfish configurado, usuarios por defecto, coach web disponible, número de partidas. |
| GET | `/api/games?user=` | Partidas (más recientes primero) con estado de análisis, recuento de errores y ACPL. |
| GET | `/api/games/{id}` | Partida completa: datos, jugadas con FEN, evaluaciones, clasificación, mejor jugada y línea corta. |
| GET | `/api/users/{usuario}/report` | Informe del jugador: ACPL, errores por tipo y por fase, partidas con más errores. |
| POST | `/api/imports` | Importa de Chess.com, Lichess o texto PGN (tarea en segundo plano). |
| POST | `/api/analyses` | Analiza una partida o las pendientes de un usuario (tarea en segundo plano). |
| GET | `/api/jobs/{id}` | Progreso y resultado de una tarea. |
| POST | `/api/engine/evaluate` | Evalúa una posición (FEN) con Stockfish. |
| POST | `/api/engine/move` | Evalúa una jugada en una posición («¿y si…?»). |
| POST | `/api/coach/sessions` | Abre una sesión del coach por API (solo con clave). |
| POST | `/api/coach/sessions/{id}/messages` | Envía una pregunta; la respuesta llega en streaming (SSE). |

Las consultas al motor aceptan `game_id` para analizar a la misma profundidad que el análisis guardado.

## Páginas

- **Partidas**: lista con filtro por usuario, estado y errores; botón para analizar las pendientes.
- **Importar**: Chess.com, Lichess o PGN (archivo o texto pegado), con barra de progreso y opción de analizar al terminar.
- **Partida**: tablero con navegación (botones y flechas del teclado), flechas de la jugada hecha y la mejor, barra de evaluación, gráfica de probabilidad de victoria (clic para ir a una jugada), lista de jugadas coloreada por tipo de error, detalle de la jugada, momentos críticos y modo explorador (mover piezas y que Stockfish evalúe la jugada). Panel del coach.
- **Informe**: resumen del jugador, errores por fase y partidas con más errores.

## Pruebas

- Backend: pytest con `TestClient`, motor guionizado, transporte HTTP simulado y cliente de Anthropic falso.
- Frontend: `tsc` (tipos), Vitest (funciones puras) y compilación de producción.
- Verificación manual en el navegador con la base de datos real y Stockfish.
