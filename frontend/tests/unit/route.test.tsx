import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RouteLine } from "@/components/route/RouteLine";
import { RouteMap } from "@/components/route/RouteMap";
import type { StatusEvent } from "@/lib/api";

import { a11yViolations } from "./axe";

const ev = (id: string, from: string | null, to: string, extra: Partial<StatusEvent> = {}): StatusEvent => ({
  id,
  old_status: from,
  new_status: to,
  evidence_type: null,
  evidence_reference: null,
  reason: null,
  actor: "user:u1",
  correction: false,
  timestamp: "2026-05-01T10:00:00Z",
  ...extra,
});

describe("RouteLine", () => {
  it("describes progress for screen readers", () => {
    render(<RouteLine status="submitted" />);
    expect(screen.getByRole("img")).toHaveAccessibleName("Sent to specialist (stop 4 of 7)");
  });

  it("shows where an exception branched off", () => {
    render(<RouteLine status="exception" progress="ready" />);
    expect(screen.getByRole("img")).toHaveAccessibleName("Exception after ready (stop 3 of 7)");
  });

  it("marks completed care", () => {
    render(<RouteLine status="completed" />);
    expect(screen.getByRole("img")).toHaveAccessibleName("Care completed (7 of 7)");
  });
});

describe("RouteMap", () => {
  const events = [
    ev("1", null, "imported", { evidence_type: "source_record", actor: "system:x" }),
    ev("2", "imported", "needs_review"),
    ev("3", "needs_review", "ready", { evidence_type: "package_approval", evidence_reference: "package:p1" }),
  ];

  it("shows evidence on reached stops and agent proposals as not done", async () => {
    const { container } = render(
      <RouteMap
        status="ready"
        progress="ready"
        events={events}
        names={{ u1: "Priya Raman" }}
        proposals={[{ approvalId: "a1", tool: "transmit_referral_package", reason: "Package approved." }]}
      />,
    );
    const list = screen.getByRole("list", { name: "Referral route" });
    const current = within(list).getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveTextContent("Ready to send");
    expect(current).toHaveTextContent("Package approved");
    expect(screen.getByText(/Agent proposes: Send package to specialist/)).toBeInTheDocument();
    expect(screen.getByText(/Not done yet/)).toBeInTheDocument();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it("draws exceptions and returns as branches", () => {
    render(
      <RouteMap
        status="needs_review"
        progress="needs_review"
        events={[
          ...events.slice(0, 2),
          ev("4", "needs_review", "exception", { reason: "Identity mismatch" }),
          ev("5", "exception", "needs_review"),
        ]}
      />,
    );
    expect(screen.getByText("Identity mismatch")).toBeInTheDocument();
    expect(screen.getByText(/Back in review/)).toBeInTheDocument();
  });
});
