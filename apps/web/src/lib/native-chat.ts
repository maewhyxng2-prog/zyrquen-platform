import type { ConversationMessage } from "./types";

export const MAX_NATIVE_PROMPT_LENGTH = 4096;

export function buildNativeInferencePrompt(
  history: ConversationMessage[],
  currentPrompt: string,
): string {
  const formattedCurrent = `user: ${currentPrompt}\nassistant:`;
  let prompt =
    formattedCurrent.length <= MAX_NATIVE_PROMPT_LENGTH
      ? formattedCurrent
      : currentPrompt;

  for (let index = history.length - 1; index >= 0; index -= 1) {
    const message = history[index];
    const candidate = `${message.role}: ${message.content}\n${prompt}`;
    if (candidate.length > MAX_NATIVE_PROMPT_LENGTH) {
      break;
    }
    prompt = candidate;
  }

  return prompt;
}

export async function consumeNativeInferenceStream(
  stream: ReadableStream<Uint8Array>,
  onText: (text: string) => void,
): Promise<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let output = "";
  let sawFinalChunk = false;
  let sawDone = false;

  function consumeEvent(eventText: string) {
    const data = eventText
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");

    if (!data) {
      return;
    }
    if (data === "[DONE]") {
      sawDone = true;
      return;
    }

    let payload: unknown;
    try {
      payload = JSON.parse(data);
    } catch {
      throw new Error("Native inference returned malformed stream data");
    }

    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("Native inference returned malformed stream data");
    }

    const event = payload as Record<string, unknown>;
    if (typeof event.error === "string" && event.error) {
      throw new Error(event.error);
    }
    if (typeof event.text !== "string" || typeof event.is_final !== "boolean") {
      throw new Error("Native inference returned an invalid stream event");
    }

    if (event.text) {
      output += event.text;
      onText(output);
    }
    if (event.is_final) {
      sawFinalChunk = true;
    }
  }

  try {
    while (!sawDone) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer = (buffer + decoder.decode(value, { stream: true })).replace(
        /\r\n/g,
        "\n",
      );
      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        consumeEvent(buffer.slice(0, separator));
        buffer = buffer.slice(separator + 2);
        separator = buffer.indexOf("\n\n");
      }
    }

    buffer = (buffer + decoder.decode()).replace(/\r\n/g, "\n");
    if (buffer.trim()) {
      consumeEvent(buffer);
    }

    if (!sawFinalChunk || !sawDone) {
      throw new Error("Native inference stream ended before completion");
    }
    return output;
  } finally {
    reader.releaseLock();
  }
}
