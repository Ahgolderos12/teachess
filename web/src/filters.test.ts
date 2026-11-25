import { describe, expect, it } from "vitest";

import { describeFilter, filterQuery, patchFilter, readFilter, writeFilter } from "./filters";

describe("stats filters", () => {
  it("round-trips through URL params, with a prefix for group B", () => {
    const params = writeFilter(new URLSearchParams("tab=x"), { color: "white", last: 20, offset: 0 });
    const both = writeFilter(params, { day_block: 18, opening: "Sicilian" }, "b_");
    expect(both.get("tab")).toBe("x");
    expect(both.has("offset")).toBe(false);
    expect(readFilter(both)).toEqual({ color: "white", last: 20 });
    expect(readFilter(both, "b_")).toEqual({ day_block: 18, opening: "Sicilian" });
  });

  it("patches, removes and describes filters", () => {
    const filter = patchFilter({ color: "black", weekday: 6 }, { weekday: undefined, min_gap: 26, max_gap: 99 });
    expect(filter).toEqual({ color: "black", min_gap: 26, max_gap: 99 });
    expect(describeFilter(filter).map((chip) => chip.label)).toEqual(["con negras", "rival entre 26 y 99"]);
    expect(filterQuery({ weekday: 0 })).toBe("weekday=0");
  });
});
