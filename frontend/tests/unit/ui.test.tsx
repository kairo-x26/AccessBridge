import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApprovalActions } from "@/app/(app)/referrals/[id]/ApprovalActions";
import { EvidenceChip, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { ToastProvider } from "@/components/ui/Toast";

import { a11yViolations } from "./axe";

afterEach(() => vi.restoreAllMocks());

describe("primitives", () => {
  it("wires labels, hints and errors to the control", async () => {
    const { container } = render(
      <Field label="Member ID" hint="As printed on the card" error="Required">
        {(p) => <input {...p} className={inputClass} />}
      </Field>,
    );
    const input = screen.getByLabelText("Member ID");
    expect(input).toHaveAccessibleDescription("As printed on the card Required");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(await a11yViolations(container)).toEqual([]);
  });

  it("busy buttons are disabled and announced", () => {
    render(<Button busy>Save</Button>);
    const b = screen.getByRole("button", { name: "Save" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
  });

  it("labels statuses and evidence in words, not color alone", () => {
    render(
      <>
        <StatusBadge status="exception" />
        <EvidenceChip type="consult_note" proposed />
        <Notice tone="error">Broken</Notice>
      </>,
    );
    expect(screen.getByText("Exception")).toBeInTheDocument();
    expect(screen.getByText("Consult note")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
  });
});

describe("ApprovalActions", () => {
  it("requires a reason before rejecting", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ decision: "rejected" }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const done = vi.fn();
    render(
      <ToastProvider>
        <ApprovalActions approvalId="apr_1" onDone={done} />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Reject proposal" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason for rejecting"), "Wrong office");
    await userEvent.click(confirm);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/approvals/apr_1/decision",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ decision: "rejected", reason: "Wrong office" }) }),
    );
    expect(done).toHaveBeenCalled();
  });
});
