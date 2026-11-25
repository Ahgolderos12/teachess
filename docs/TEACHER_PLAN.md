# Plan: el Teacher (profesor proactivo)

Última actualización: 2026-11-25. Estado: **pasos 1-5 hechos** (rama `teacher`).

Decisiones del usuario (2026-11-25): empezar por diagnóstico + prompt `teacher`; el Informe
pasa a ser la pestaña Estadísticas (ampliada); sincronización al arrancar `serve` y cada 6 h,
con botón para sincronizar ya; analizar ya las partidas pendientes (hecho: 100 de 100).

## Por qué

Hoy Teachess es un analizador de partidas como cualquier otro: el jugador tiene que pedir
explicaciones. El objetivo es un profesor parecido a uno humano que **ya sabe por dónde
empezar la lección**, porque ha visto tus partidas recientes y tus estadísticas, y que la
orienta él solo.

Ejemplos de cómo debería abrir una lección:

- «En tus últimas 10 partidas, 4 derrotas se decidieron antes de la jugada 12. Eso apunta a
  las aperturas: te propongo empezar por esta, y aquí tienes dos posiciones tuyas para
  practicar.»
- «Has perdido 3 partidas en los últimos minutos: al final jugabas el triple de rápido que al
  principio y ahí llegaron los errores graves. Vamos a hablar de gestión del tiempo.»
- O cualquier otro hilo que el propio profesor vea en las estadísticas (conversión de
  ventajas, finales, una apertura concreta…).

## Ideas apuntadas (del usuario)

1. **Pestaña «Teacher»** en la web con la terminal de Claude Code (vía MCP, coste 0) ya
   preparada: arranca sabiendo qué decirte y con qué empezar la lección.
2. **Importación automática** de Chess.com cada cierto tiempo (y análisis automático de lo
   importado), para que el profesor siempre trabaje con las últimas partidas.
3. **Lecciones guiadas por patrones**: derrotas antes de la jugada 10 → aperturas
   (propuestas concretas + ejemplos prácticos); derrotas por apuro de tiempo → gestión del
   reloj; libertad para que el profesor elija el tema según lo que vea.
4. **Pestaña de estadísticas masivas**: mantener un apartado como el Informe, dedicado solo
   a estadísticas, **con muchas más estadísticas de todo tipo** (ver abajo).

## Ideas apuntadas (propuestas de Claude)

5. **Diagnóstico determinista antes que LLM**: los patrones («pierdes en la apertura», «te
   apuras al final») los detecta código Python sobre la base de datos, con evidencias
   (partida, jugada, reloj). El profesor solo elige, explica y conversa. Así se cumple «el
   motor calcula, el LLM explica»: el LLM no saca conclusiones estadísticas inventadas.
6. **Memoria de lecciones** (adelanta parte de la Fase 3): al terminar, el profesor guarda un
   resumen estructurado (tema trabajado, qué dijo el jugador, deberes). La siguiente lección
   empieza por ahí: «La semana pasada trabajamos la Siciliana; desde entonces la has jugado 3
   veces y…».
7. **Ejercicios desde tus propias partidas**: posiciones donde fallaste convertidas en «encuentra
   la jugada», validadas con Stockfish (adelanta parte de la Fase 4).
8. **Modo socrático por defecto** en el Teacher: antes de enseñar la jugada buena, pregunta
   «¿qué pensabas aquí?» y guarda la respuesta en la memoria.
9. **Más adelante**: plan semanal, repetición espaciada, repertorio de aperturas, motor de
   errores humanos tipo Maia.

## Estadísticas a añadir (pestaña «Estadísticas»)

Datos que ya tenemos: resultado, color, ritmo, fecha, ELO de ambos, ECO y nombre de apertura,
motivo de fin (`Termination`: abandono, tiempo, jaque mate…), reloj por jugada (`%clk`),
clasificación y pérdida % por jugada, fase.

- **Resultados**: % victorias/tablas/derrotas global, por color, por ritmo, por mes; rachas;
  rendimiento contra rivales de más/menos ELO.
- **Evolución**: ELO en el tiempo, precisión/ACPL por partida y media móvil, errores graves
  por partida en el tiempo.
- **Cómo terminan**: derrotas por abandono, tiempo, mate; victorias igual; jugada media en que
  se decide la partida.
- **Aperturas**: rendimiento por ECO/apertura y color, errores en las primeras 10-15 jugadas,
  aperturas más jugadas y con peor resultado.
- **Fases**: errores por fase normalizados por número de jugadas, pérdida media por fase.
- **Tiempo**: tiempo medio por jugada por fase, reloj restante cuando se cometen los errores,
  errores con menos del 10 % del tiempo, derrotas por tiempo, jugadas muy rápidas en momentos
  críticos, tiempo gastado en la apertura.
- **Conversión y resistencia**: partidas con ventaja decisiva que no se ganaron, partidas
  perdidas que se salvaron o remontaron.
- **Duración**: número de jugadas medio, por resultado.
- **Por hora/día** (si hay suficientes partidas): rendimiento según hora del día.

Todas se calculan en Python (`patterns/`), las sirve la API y la web solo las pinta.

## Arquitectura propuesta

```
src/teachess/patterns/      # nuevo: estadísticas y detectores de patrones (funciones puras)
  stats.py                  #   estadísticas agregadas para la pestaña Estadísticas
  detectors.py              #   hallazgos: derrotas tempranas, apuro de tiempo, conversión…
src/teachess/coach/
  mcp_server.py             # + herramientas get_player_diagnosis / get_player_stats
                            # + prompt MCP `teacher` (sin partida: abre la lección solo)
  prompts.py                # + prompt del profesor proactivo
src/teachess/api/
  app.py                    # + /api/users/{u}/stats, /api/users/{u}/diagnosis
  terminal.py               # nuevo: WebSocket ↔ PTY que lanza `claude` (pestaña Teacher)
  sync.py                   # nuevo: importación + análisis automáticos periódicos
web/src/pages/
  StatsPage.tsx             # pestaña Estadísticas (sustituye o amplía el Informe)
  TeacherPage.tsx           # terminal embebida (xterm.js)
```

Cada hallazgo del diagnóstico tiene: tipo, impacto (para ordenar), cifras medidas,
evidencias (`game_id`, jugada, reloj) y tema de lección sugerido. El prompt `teacher` le
pasa al modelo el diagnóstico + la memoria y le pide que abra la lección con el hallazgo de
más impacto (o con el que el jugador prefiera).

### La terminal embebida: lo que enseñó la prueba real

- Pasar `/mcp__teachess__teacher` como prompt inicial no funciona: Claude Code lo procesa
  antes de conectar el servidor MCP («Unknown command»). Solución: instrucciones en el prompt
  de sistema y el primer mensaje tecleado cuando el servidor MCP avisa de que está listo.
- La extensión de Chrome seguía disponible pese a `--strict-mcp-config`: se añadieron
  `--no-chrome`, `--disable-slash-commands` y `--permission-mode dontAsk`.
- El modelo reordenó las filas del diagrama de texto (tablero volteado): de ahí el tablero
  real junto a la terminal, alimentado por `show_position`.
- El uvicorn instalado no traía soporte de WebSocket: se añadió `websockets`.
- Con Haiku el profesor funciona pero es flojo (llegó a escribir sintaxis de herramientas
  como texto); `TEACHESS_TEACHER_MODEL` permite usar otro modelo.

### La terminal embebida: notas de diseño

- Técnica: `pty` de la biblioteca estándar de Python + WebSocket en FastAPI + `xterm.js` en
  la web. Lanza `claude` en la carpeta del proyecto con el prompt `/mcp__teachess__teacher`.
- **Uso permitido**: es Claude Code interactivo usado por ti en tu equipo, como en cualquier
  terminal; no se conecta el login de la suscripción a la app. Por eso no sirve para otros
  usuarios: cuando haya más, el Teacher usará la vía de la API (`teachess coach`).
  Descartado: manejar `claude -p` desde la app con un chat propio (se parece demasiado a
  integrar la suscripción en un producto).
- **Seguridad**: un WebSocket no está protegido por CORS; cualquier web abierta en tu
  navegador podría intentar conectarse a `127.0.0.1:8000` y manejar Claude Code. Hace falta
  comprobar la cabecera `Origin` y un token por arranque, y lanzar `claude` limitado a las
  herramientas `mcp__teachess__*` (sin Bash ni edición de archivos).

## Orden propuesto

1. ✅ **Diagnóstico** (`patterns/facts.py`, `patterns/diagnosis.py`): la base de todo lo
   demás. Las estadísticas masivas (`patterns/stats.py`) van con el paso 3.
2. ✅ **Prompt MCP `teacher`** + herramientas `get_player_diagnosis` y `show_position`.
   Falta la primera clase real en Claude Code y ajustar el prompt con lo que se vea.
3. ✅ **Pestaña Estadísticas** (`patterns/stats.py`), sustituye al Informe.
4. ✅ **Pestaña Teacher**: terminal embebida + tablero de la clase. Probada con Claude Code
   real en Chrome: abre la clase sola, muestra la posición en el tablero y da pistas sin
   revelar la jugada.
5. ✅ **Sincronización automática** (al arrancar `serve` y cada 6 h, botón en la cabecera).
6. **Memoria de lecciones** (Fase 3).
7. Ejercicios desde tus partidas, plan semanal (Fase 4).

## Primer diagnóstico real (100 partidas analizadas, ventana de 50)

1. Medio juego: 9,5 errores serios cada 100 jugadas frente a 3,4 en el resto; 13 partidas
   decididas ahí.
2. Ventajas que se escapan: 8 partidas con posición ganadora (≥ 80 %) perdidas.
3. Derrotas en la apertura: 5 de 21 no ganadas, decididas antes de la jugada 16.
4. Errores rápidos: 17 de 96 errores serios jugados en segundos con tiempo de sobra.
5. Apuros de tiempo: 3 derrotas por tiempo.
6. Aperturas con blancas con mal resultado (Francesa, Gambito de Dama, Nimzowitsch: 25 %).

Con la ventana por defecto (20) salen 1, 4 y 6; el profesor puede pedir más partidas con
`get_player_diagnosis`.
