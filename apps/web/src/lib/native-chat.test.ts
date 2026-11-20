import { describe, expect, it } from "vitest";

import {
  buildNativeInferencePrompt,
  consumeNativeInferenceStream,
  MAX_NATIVE_PROMPT_LENGTH,
} from "./native-chat";
import type { ConversationMessage } from "./types";

function message(
  role: ConversationMessage["role"],
  content: string,
): ConversationMessage {
  return {
    id: `${role}-${content.length}`,
    role,
    content,
    createdAt: "2026-01-01T00:00:00.000Z",
  };
}

function byteStream(value: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(value);
  return new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += 7) {
        controller.enqueue(bytes.slice(offset, offset + 7));
      }
      controller.close();
    },
  });
}

describe("Native chat prompt and stream handling", () => {
  it("includes recent turns while keeping the inference prompt within API bounds", () => {
    const history = [
      message("user", "old context ".repeat(500)),
      message("assistant", "recent answer"),
    ];

    const prompt = buildNativeInferencePrompt(history, "follow-up");

    expect(prompt).toContain("assistant: recent answer");
    expect(prompt).toContain("user: follow-up");
    expect(prompt).not.toContain("old context");
    expect(prompt.length).toBeLessThanOrEqual(MAX_NATIVE_PROMPT_LENGTH);
  });

  it("parses chunked UTF-8 SSE events and returns the model output", async () => {
    const events = [
      { text: "สวัสดี", index: 0, is_final: false },
      { text: "ครับ", index: 1, is_final: false },
      { text: "", index: 2, is_final: true },
    ]
      .map((event) => `data: ${JSON.stringify(event)}\r\n\r\n`)
      .join("");
    const stream = byteStream(`${events}data: [DONE]\r\n\r\n`);
    const updates: string[] = [];

    const output = await consumeNativeInferenceStream(stream, (text) => {
      updates.push(text);
    });

    expect(output).toBe("สวัสดีครับ");
    expect(updates).toEqual(["สวัสดี", "สวัสดีครับ"]);
  });

  it("surfaces backend stream errors instead of accepting a partial success", async () => {
    const stream = byteStream(
      'data: {"error":"Native model is unavailable"}\n\n',
    );

    await expect(
      consumeNativeInferenceStream(stream, () => undefined),
    ).rejects.toThrow("Native model is unavailable");
  });
});
