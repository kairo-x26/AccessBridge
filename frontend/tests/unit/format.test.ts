import { describe, expect, it } from "vitest";

import { actorLabel, label, relative, ROUTE, STATUS_LABEL, SPECIALTY_LABEL } from "@/lib/format";

describe("format", () => {
  it("covers every route stop with a status label", () => {
    expect(ROUTE.map((r) => r.status)).toEqual([
      "imported", "needs_review", "ready", "submitted", "acknowledged", "scheduled", "completed",
    ]);
    for (const r of ROUTE) expect(STATUS_LABEL[r.status]).toBeTruthy();
  });

  it("falls back to readable text for unknown keys", () => {
    expect(label(SPECIALTY_LABEL, "behavioral_health")).toBe("Behavioral health");
    expect(label(SPECIALTY_LABEL, "sleep_medicine")).toBe("Sleep medicine");
    expect(label(SPECIALTY_LABEL, null)).toBe("—");
  });

  it("names actors without exposing ids", () => {
    expect(actorLabel("user:usr_1", { usr_1: "Priya Raman" })).toBe("Priya Raman");
    expect(actorLabel("user:usr_2")).toBe("Staff member");
    expect(actorLabel("agent:run_1")).toBe("AccessBridge agent");
    expect(actorLabel("system:fhir-reconciler")).toBe("Specialist system");
  });

  it("formats relative times in both directions", () => {
    const now = Date.parse("2026-06-01T12:00:00Z");
    expect(relative("2026-05-30T12:00:00Z", now)).toBe("2 days ago");
    expect(relative("2026-06-01T15:00:00Z", now)).toBe("in 3 hours");
  });
});
