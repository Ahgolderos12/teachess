import "@xterm/xterm/css/xterm.css";

import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef } from "react";

import type { TerminalMessage } from "../types";

export type TerminalState = "connecting" | "open" | "ended" | "error";

/** Read a CSS custom property from the page theme, for xterm's own colour scheme. */
function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Claude Code running as the Teacher, in an xterm.js terminal bridged over a WebSocket. */
export function TeacherTerminal({
  token,
  session,
  onState,
}: {
  token: string;
  session: number; // bump to start a new lesson
  onState: (state: TerminalState) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const stateRef = useRef(onState);
  stateRef.current = onState;

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const term = new Terminal({
      fontFamily: cssVar("--mono", "Menlo, monospace"),
      fontSize: 14,
      cursorBlink: true,
      convertEol: false,
      theme: {
        background: cssVar("--terminal-bg", "#111514"),
        foreground: cssVar("--terminal-fg", "#e6ebe8"),
        cursor: cssVar("--accent", "#3fb592"),
        selectionBackground: cssVar("--accent-soft", "#1d3a31"),
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(element);
    fit.fit();
    term.focus();

    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const params = new URLSearchParams({
      token,
      cols: String(term.cols),
      rows: String(term.rows),
    });
    const socket = new WebSocket(`${scheme}://${window.location.host}/api/teacher/terminal?${params}`);
    stateRef.current("connecting");
    let ended = false;

    socket.onopen = () => stateRef.current("open");
    socket.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as TerminalMessage;
      if (message.type === "output") term.write(message.data);
      else {
        ended = true;
        term.write("\r\n\x1b[2m— Clase terminada. Pulsa «Nueva clase» para empezar otra. —\x1b[0m\r\n");
        stateRef.current("ended");
      }
    };
    socket.onclose = (event) => {
      if (ended) return;
      if (event.code === 4403 || event.code === 4503) stateRef.current("error");
      else stateRef.current("ended");
    };
    socket.onerror = () => stateRef.current("error");

    const input = term.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "input", data }));
      }
    });
    const resize = () => {
      fit.fit();
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);

    return () => {
      observer.disconnect();
      input.dispose();
      socket.close();
      term.dispose();
    };
  }, [token, session]);

  return <div className="terminal" ref={container} />;
}
