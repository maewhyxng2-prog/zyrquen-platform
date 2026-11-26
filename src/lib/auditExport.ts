export type AuditEvent = {
  id: string;
  created_at: string;
  actor_id?: string;
  actor_email?: string;
  action: string;
  target?: string;
  outcome?: string;
  details_json?: string | null;
};

const ALWAYS_EXCLUDED_KEYS = new Set([
  "ip",
  "ip_address",
  "remote_addr",
  "user_agent",
  "useragent",
]);
const SECRET_KEY_PATTERN = /(token|api[_-]?key|password|secret|authorization|cookie|session)/i;
const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
const PHONE_PATTERN = /(?<!\d)(?:\+?66|0)[ -]?(?:\d[ -]?){8,9}(?!\d)/g;

export function maskEmail(value: string): string {
  return value.replace(EMAIL_PATTERN, (email) => {
    const at = email.indexOf("@");
    if (at <= 0) return "[REDACTED]";
    const local = email.slice(0, at);
    return `${local.length > 1 ? "**" : "*"}@${email.slice(at + 1)}`;
  });
}

function redactString(value: string): string {
  return maskEmail(value).replace(PHONE_PATTERN, (phone) => {
    const digits = phone.replace(/\D/g, "");
    return digits.length >= 4 ? `${digits.slice(0, 3)}-***-****` : "[REDACTED]";
  });
}

function redactValue(key: string, value: unknown): unknown {
  const normalizedKey = key.toLowerCase().replace(/[ -]/g, "_");
  if (ALWAYS_EXCLUDED_KEYS.has(normalizedKey) || SECRET_KEY_PATTERN.test(normalizedKey)) {
    return "[REDACTED]";
  }
  if (normalizedKey.includes("email") && typeof value === "string") {
    return redactString(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactValue("", item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([childKey, childValue]) => [
        childKey,
        redactValue(childKey, childValue),
      ])
    );
  }
  return typeof value === "string" ? redactString(value) : value;
}

export function redactAuditRow(row: AuditEvent): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(row).map(([key, value]) => [key, redactValue(key, value)])
  );
}

export function isPiiAuditEvent(event: AuditEvent): boolean {
  return /PII/i.test(event.action);
}

export function toSafeAuditCsv(rows: AuditEvent[]): string {
  const header = ["เวลา", "ผู้ดำเนินการ", "เหตุการณ์", "เป้าหมาย", "ผลลัพธ์"];
  const lines = rows
    .filter(isPiiAuditEvent)
    .map((row) => {
      const safe = redactAuditRow(row);
      return [
        safe.created_at,
        safe.actor_email ?? safe.actor_id ?? "-",
        safe.action,
        safe.target ?? "-",
        safe.outcome ?? "-",
      ];
    });
  return [header, ...lines].map((line) => line.map(csvCell).join(",")).join("\r\n");
}

function csvCell(value: unknown): string {
  let text = value == null ? "" : String(value);
  // Prevent spreadsheet formula execution for untrusted audit text.
  if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export function toSafeAuditJson(rows: AuditEvent[]): string {
  return JSON.stringify(rows.filter(isPiiAuditEvent).map(redactAuditRow), null, 2);
}

export function downloadText(filename: string, text: string, mimeType: string): void {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
