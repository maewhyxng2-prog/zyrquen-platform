import { describe, expect, it } from "vitest";
import { filterAndGroupConversations } from "./conversation-groups";
import type { Conversation } from "./types";

function makeConversation(
  id: string,
  title: string,
  updatedAt: string,
): Conversation {
  return {
    id,
    title,
    createdAt: updatedAt,
    updatedAt,
    messageCount: 2,
    messages: [],
  };
}

describe("filterAndGroupConversations", () => {
  const now = new Date(2026, 10, 24, 14, 0, 0);
  const items: Conversation[] = [
    makeConversation(
      "c1",
      "สรุปสถาปัตยกรรม Native Core",
      new Date(2026, 10, 24, 9, 30, 0).toISOString(),
    ),
    makeConversation(
      "c2",
      "วางแผนทดสอบ RBAC เมื่อวาน",
      new Date(2026, 10, 23, 18, 0, 0).toISOString(),
    ),
    makeConversation(
      "c3",
      "ประเมิน Generalization 4-Split",
      new Date(2026, 10, 20, 11, 0, 0).toISOString(),
    ),
    makeConversation(
      "c4",
      "บันทึกโครงสร้างฐานข้อมูลเก่า",
      new Date(2026, 10, 10, 8, 0, 0).toISOString(),
    ),
  ];

  it("groups conversations into today, yesterday, 7 days, and older buckets", () => {
    const groups = filterAndGroupConversations(items, "", now);
    expect(groups.map((g) => g.key)).toEqual([
      "today",
      "yesterday",
      "week",
      "older",
    ]);
    expect(groups[0]?.items.map((i) => i.id)).toEqual(["c1"]);
    expect(groups[1]?.items.map((i) => i.id)).toEqual(["c2"]);
    expect(groups[2]?.items.map((i) => i.id)).toEqual(["c3"]);
    expect(groups[3]?.items.map((i) => i.id)).toEqual(["c4"]);
  });

  it("filters by case-insensitive title search and omits empty groups", () => {
    const groups = filterAndGroupConversations(items, "rbac", now);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.key).toBe("yesterday");
    expect(groups[0]?.items.map((i) => i.id)).toEqual(["c2"]);
  });

  it("returns empty array when search matches nothing", () => {
    const groups = filterAndGroupConversations(items, "ไม่มีหัวข้อนี้", now);
    expect(groups).toEqual([]);
  });
});
