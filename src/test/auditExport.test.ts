import { describe, expect, it } from 'vitest';
import {
  isPiiAuditEvent,
  redactAuditRow,
  toSafeAuditCsv,
  toSafeAuditJson,
} from '../lib/auditExport';

const piiEvent = {
  id: 'audit-1',
  created_at: '2026-11-26T08:00:00.000Z',
  actor_id: 'user-1',
  actor_email: 'private.person@example.com',
  action: 'PII_REDACTED',
  target: 'Contact private.person@example.com / 0812345678',
  outcome: 'REDACTED',
  details_json: JSON.stringify({
    email: 'private.person@example.com',
    phone: '0812345678',
    ip: '192.0.2.10',
    user_agent: 'Sensitive browser string',
    api_key: 'secret-value',
    note: 'Contact private.person@example.com from 192.0.2.10',
  }),
};

describe('PII-safe audit export', () => {
  it('recognizes only PII audit events for the default export scope', () => {
    expect(isPiiAuditEvent(piiEvent)).toBe(true);
    expect(isPiiAuditEvent({ ...piiEvent, action: 'LOGIN' })).toBe(false);
    expect(toSafeAuditCsv([piiEvent, { ...piiEvent, id: '2', action: 'LOGIN' }])).toContain('PII_REDACTED');
    expect(toSafeAuditCsv([piiEvent, { ...piiEvent, id: '2', action: 'LOGIN' }])).not.toContain('LOGIN');
  });

  it('masks email and phone and omits IP and User-Agent fields recursively', () => {
    const safe = redactAuditRow(piiEvent);
    expect(safe.actor_email).toBe('**@example.com');
    expect(String(safe.target)).not.toContain('private.person@example.com');
    expect(String(safe.target)).not.toContain('0812345678');
    const details = JSON.parse(String(safe.details_json));
    expect(details.email).toBe('**@example.com');
    expect(details.phone).toContain('***');
    expect(details).not.toHaveProperty('ip');
    expect(details).not.toHaveProperty('user_agent');
    expect(details.api_key).toBe('[REDACTED]');
    expect(JSON.stringify(details)).not.toContain('192.0.2.10');
    expect(JSON.stringify(details)).not.toContain('Sensitive browser string');
  });

  it('redacts JSON export and neutralizes spreadsheet formula cells', () => {
    const json = toSafeAuditJson([piiEvent]);
    expect(json).not.toContain('private.person@example.com');
    expect(json).not.toContain('192.0.2.10');
    const csv = toSafeAuditCsv([{ ...piiEvent, target: '=HYPERLINK("https://bad.invalid")' }]);
    expect(csv).toContain("'=HYPERLINK(""https://bad.invalid"")");
  });

  it('can export non-PII rows only when the caller explicitly disables the PII-only filter', () => {
    const login = { ...piiEvent, id: 'login-1', action: 'LOGIN' };
    expect(toSafeAuditJson([login])).toBe('[]');
    expect(toSafeAuditJson([login], false)).toContain('"LOGIN"');
  });
});
