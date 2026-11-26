import type { Conversation } from "./types";

export type ConversationGroupKey = "today" | "yesterday" | "week" | "older";

export type ConversationDateGroup = {
  key: ConversationGroupKey;
  label: string;
  items: Conversation[];
};

const groupOrder: { key: ConversationGroupKey; label: string }[] = [
  { key: "today", label: "วันนี้" },
  { key: "yesterday", label: "เมื่อวาน" },
  { key: "week", label: "7 วันล่าสุด" },
  { key: "older", label: "ก่อนหน้านี้" },
];

function startOfLocalDayMs(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function classifyConversationDateGroup(
  updatedAt: string,
  now = new Date(),
): ConversationGroupKey {
  const parsedMs = Date.parse(updatedAt);
  if (Number.isNaN(parsedMs)) {
    return "older";
  }
  const todayStart = startOfLocalDayMs(now);
  const itemStart = startOfLocalDayMs(new Date(parsedMs));
  const diffDays = Math.round((todayStart - itemStart) / (24 * 60 * 60 * 1000));

  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return "week";
  return "older";
}

export function filterAndGroupConversations(
  conversations: Conversation[],
  searchQuery: string,
  now = new Date(),
): ConversationDateGroup[] {
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filtered = normalizedQuery
    ? conversations.filter((item) =>
        item.title.toLowerCase().includes(normalizedQuery),
      )
    : conversations;

  const sorted = [...filtered].sort(
    (a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt),
  );

  const buckets = new Map<ConversationGroupKey, Conversation[]>();
  for (const { key } of groupOrder) {
    buckets.set(key, []);
  }

  for (const conversation of sorted) {
    const key = classifyConversationDateGroup(conversation.updatedAt, now);
    buckets.get(key)?.push(conversation);
  }

  return groupOrder
    .map(({ key, label }) => ({
      key,
      label,
      items: buckets.get(key) ?? [],
    }))
    .filter((group) => group.items.length > 0);
}
