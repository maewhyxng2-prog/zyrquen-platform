export function belongsToAccount(
  dataOwnerId: string | null,
  activeUserId: string | null | undefined,
): boolean {
  return Boolean(dataOwnerId && activeUserId && dataOwnerId === activeUserId);
}

export function quotaPercent(
  used: number,
  limit: number | null,
): number | null {
  if (limit === null) return null;
  if (!Number.isFinite(used) || !Number.isFinite(limit) || used < 0 || limit < 0) {
    return null;
  }
  if (limit === 0) return used > 0 ? 100 : 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

export function quotaState(used: number, limit: number): string {
  if (used > limit) return "เกินขีดจำกัด";
  if (used === limit) return "ถึงขีดจำกัด";
  if (used / limit >= 0.8) return "ใกล้ถึงขีดจำกัด";
  return "อยู่ในขีดจำกัด";
}
