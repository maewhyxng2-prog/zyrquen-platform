import { describe, expect, it } from "vitest";
import {
  belongsToAccount,
  quotaPercent,
  quotaState,
} from "./user-state";

describe("account-scoped settings state", () => {
  it("does not display account data after the active user changes", () => {
    expect(belongsToAccount("user-a", "user-a")).toBe(true);
    expect(belongsToAccount("user-a", "user-b")).toBe(false);
    expect(belongsToAccount("user-a", null)).toBe(false);
  });
});

describe("quota presentation", () => {
  it("does not derive a percentage when the backend has no limit", () => {
    expect(quotaPercent(120, null)).toBeNull();
  });

  it("caps the visual percentage but preserves the exceeded state", () => {
    expect(quotaPercent(120, 100)).toBe(100);
    expect(quotaState(120, 100)).toBe("เกินขีดจำกัด");
  });

  it("handles a backend-confirmed zero limit without division", () => {
    expect(quotaPercent(0, 0)).toBe(0);
    expect(quotaPercent(1, 0)).toBe(100);
    expect(quotaState(0, 0)).toBe("ถึงขีดจำกัด");
  });
});
