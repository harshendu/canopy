import { describe, expect, it } from "vitest";

import { horizon } from "./horizon";

const NOW = new Date("2026-05-01T00:00:00Z").getTime();

describe("horizon", () => {
  it("buckets by days from now", () => {
    expect(horizon(null, NOW)).toBe("later");
    expect(horizon("2026-05-10", NOW)).toBe("now"); // +9d
    expect(horizon("2026-06-15", NOW)).toBe("next"); // +45d
    expect(horizon("2026-12-01", NOW)).toBe("later"); // +214d
  });

  it("treats overdue as now", () => {
    expect(horizon("2026-04-01", NOW)).toBe("now"); // -30d
  });
});
