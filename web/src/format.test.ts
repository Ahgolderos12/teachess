import { describe, expect, it } from "vitest";

import { errorMessage, parseSse } from "./api";
import {
  evalBarShare,
  formatAcpl,
  formatClock,
  formatDate,
  formatTimeControl,
  uciSquares,
} from "./format";

describe("format", () => {
  it("formats dates in Spanish order", () => {
    expect(formatDate("2026-10-14T13:30:31+00:00")).toBe("14/10/2026");
    expect(formatDate("2026-10-01")).toBe("01/10/2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not a date")).toBe("not a date");
  });

  it("formats time controls", () => {
    expect(formatTimeControl("600+5")).toBe("10+5");
    expect(formatTimeControl("180")).toBe("3 min");
    expect(formatTimeControl("90+30")).toBe("1.5+30");
    expect(formatTimeControl("30")).toBe("30s");
    expect(formatTimeControl("1/86400")).toBe("Diaria");
    expect(formatTimeControl(null)).toBe("—");
    expect(formatTimeControl("-")).toBe("—");
  });

  it("formats clocks", () => {
    expect(formatClock(598)).toBe("9:58");
    expect(formatClock(3723)).toBe("1:02:03");
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(null)).toBe("");
  });

  it("formats ACPL", () => {
    expect(formatAcpl(56.6)).toBe("57");
    expect(formatAcpl(null)).toBe("—");
  });

  it("parses UCI moves into squares", () => {
    expect(uciSquares("e2e4")).toEqual(["e2", "e4"]);
    expect(uciSquares("e7e8q")).toEqual(["e7", "e8"]);
    expect(uciSquares("xx")).toBeNull();
    expect(uciSquares(null)).toBeNull();
  });

  it("keeps both sides of the eval bar visible", () => {
    expect(evalBarShare(100)).toBe(97);
    expect(evalBarShare(0)).toBe(3);
    expect(evalBarShare(52.5)).toBe(52.5);
  });
});

describe("api helpers", () => {
  it("reads FastAPI error bodies", () => {
    expect(errorMessage({ detail: "No existe la partida 4." }, 404)).toBe("No existe la partida 4.");
    expect(errorMessage({ detail: [{ msg: "a" }, { msg: "b" }] }, 422)).toBe("a · b");
    expect(errorMessage(null, 500)).toBe("Error del servidor (500).");
  });

  it("parses server-sent events across chunks", () => {
    const first = parseSse('data: {"type":"text","text":"Ho"}\n\ndata: {"type":"te');
    expect(first.events).toEqual([{ type: "text", text: "Ho" }]);
    const second = parseSse(first.rest + 'xt","text":"la"}\n\n');
    expect(second.events).toEqual([{ type: "text", text: "la" }]);
    expect(second.rest).toBe("");
    expect(parseSse("data: {broken}\n\n").events).toEqual([]);
  });
});
