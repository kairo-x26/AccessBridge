export type Status =
  | "imported"
  | "needs_review"
  | "ready"
  | "submitted"
  | "acknowledged"
  | "scheduled"
  | "completed"
  | "exception"
  | "declined"
  | "cancelled";

/** The route a referral travels, in order. Short labels are station names on the line. */
export const ROUTE: { status: Status; short: string }[] = [
  { status: "imported", short: "Imported" },
  { status: "needs_review", short: "Review" },
  { status: "ready", short: "Ready" },
  { status: "submitted", short: "Sent" },
  { status: "acknowledged", short: "Received" },
  { status: "scheduled", short: "Scheduled" },
  { status: "completed", short: "Completed" },
];

export const STATUS_LABEL: Record<Status, string> = {
  imported: "Imported",
  needs_review: "In review",
  ready: "Ready to send",
  submitted: "Sent to specialist",
  acknowledged: "Received by specialist",
  scheduled: "Appointment scheduled",
  completed: "Care completed",
  exception: "Exception",
  declined: "Declined",
  cancelled: "Cancelled",
};

export const SPECIALTY_LABEL: Record<string, string> = {
  cardiology: "Cardiology",
  dermatology: "Dermatology",
  endocrinology: "Endocrinology",
  gastroenterology: "Gastroenterology",
  neurology: "Neurology",
  orthopedics: "Orthopedics",
  ophthalmology: "Ophthalmology",
  behavioral_health: "Behavioral health",
  unsupported: "Unsupported specialty",
  unspecified: "Not stated",
};

export const EVIDENCE_LABEL: Record<string, string> = {
  source_record: "Source record",
  package_approval: "Package approved",
  transmission_receipt: "Transmission receipt",
  manual_submission_note: "Manual submission note",
  specialist_acknowledgment: "Specialist acknowledgment",
  phone_confirmation: "Phone confirmation",
  appointment_record: "Appointment record",
  patient_confirmation: "Patient confirmation",
  consult_note: "Consult note",
  specialist_completion_confirmation: "Specialist confirmation",
  fhir_task_update: "Specialist system update",
  patient_declined: "Patient declined",
  specialist_declined: "Specialist declined",
  cancellation_notice: "Cancellation notice",
  message_delivery: "Message delivery",
};

export const FIELD_LABEL: Record<string, string> = {
  patient_name: "Patient name",
  birth_date: "Date of birth",
  mrn: "Medical record number",
  phone: "Phone",
  insurance_payer: "Insurance payer",
  member_id: "Member ID",
  referring_provider: "Referring clinician",
  referring_npi: "Referring NPI",
  specialty_requested: "Specialty requested",
  reason_for_referral: "Reason for referral",
  diagnosis_code: "Diagnosis code",
};

export const TOOL_LABEL: Record<string, string> = {
  run_document_analysis: "Read documents",
  create_coordinator_task: "Create task",
  flag_exception: "Flag exception",
  transmit_referral_package: "Send package to specialist",
  send_patient_message: "Text the patient",
  record_scheduled: "Record appointment",
  propose_completion: "Mark care completed",
};

export const ROLE_LABEL: Record<string, string> = {
  admin: "Administrator",
  coordinator: "Referral coordinator",
  navigator: "Patient navigator",
  clinician: "Clinician",
  security: "Security administrator",
};

export const label = (map: Record<string, string>, key: string | null | undefined) =>
  key ? (map[key] ?? key.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase())) : "—";

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function formatDate(iso: string | null | undefined): string {
  return iso ? dateFmt.format(new Date(iso)) : "—";
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : "—";
}

export function relative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
  if (abs < 3_600_000) return rtf.format(Math.round(diff / 60_000), "minute");
  if (abs < 86_400_000) return rtf.format(Math.round(diff / 3_600_000), "hour");
  return rtf.format(Math.round(diff / 86_400_000), "day");
}

export function actorLabel(actor: string, names: Record<string, string> = {}): string {
  const [kind, id] = actor.split(":", 2);
  if (kind === "user") return names[id] ?? "Staff member";
  if (kind === "agent") return "AccessBridge agent";
  if (actor.startsWith("system:fhir")) return "Specialist system";
  if (actor.startsWith("system:messaging")) return "Messaging";
  return "System";
}
