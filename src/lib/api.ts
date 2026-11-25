export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function isAbortError(err: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  if (err instanceof DOMException && err.name === 'AbortError') return true;
  return err instanceof Error && err.name === 'AbortError';
}

export async function apiRequest<T>(
  path: string,
  options: {
    method?: string;
    token?: string | null;
    body?: unknown;
    signal?: AbortSignal;
  } = {}
): Promise<T> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    throw new ApiError('ต้องเชื่อมต่ออินเทอร์เน็ตเพื่อใช้งาน ZYRQUEN (ไม่รองรับโหมดออฟไลน์)', 0);
  }
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  };
  if (options.token && options.token !== '__cookie__') {
    headers.Authorization = `Bearer ${options.token}`;
  }

  let res: Response;
  try {
    res = await fetch(path, {
      method: options.method || 'GET',
      headers,
      credentials: 'include',
      signal: options.signal,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch (err) {
    if (isAbortError(err, options.signal)) {
      throw err;
    }
    throw new ApiError(
      'ไม่สามารถเชื่อมต่อกับ ZYRQUEN Cloud Core ได้ กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองเชื่อมต่อใหม่',
      0
    );
  }

  const data = (await res.json().catch(() => ({}))) as { error?: string } & T;
  if (!res.ok) {
    throw new ApiError(data.error || `Request failed (${res.status})`, res.status);
  }
  return data;
}

export async function streamConversationMessage<TResult>(
  conversationId: string,
  options: {
    token?: string | null;
    content: string;
    mode: string;
    attachment?: string;
    modelVariant: string;
    signal?: AbortSignal;
    onDelta?: (partialText: string) => void;
  }
): Promise<TResult> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    throw new ApiError('ต้องเชื่อมต่ออินเทอร์เน็ตเพื่อใช้งาน ZYRQUEN (ไม่รองรับโหมดออฟไลน์)', 0);
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream, application/json',
    'X-Requested-With': 'XMLHttpRequest',
  };
  if (options.token && options.token !== '__cookie__') {
    headers.Authorization = `Bearer ${options.token}`;
  }

  let res: Response;
  try {
    res = await fetch(`/api/conversations/${conversationId}/stream`, {
      method: 'POST',
      headers,
      credentials: 'include',
      signal: options.signal,
      body: JSON.stringify({
        content: options.content,
        mode: options.mode,
        attachment: options.attachment,
        modelVariant: options.modelVariant,
        metadata: {
          modelVersion: options.modelVariant,
          modelVariant: options.modelVariant,
        },
      }),
    });
  } catch (err) {
    if (isAbortError(err, options.signal)) {
      throw err;
    }
    throw new ApiError(
      'การเชื่อมต่อกับ ZYRQUEN Cloud Core ขาดหายระหว่างประมวลผล กรุณาลองเชื่อมต่อใหม่',
      0
    );
  }

  if (!res.ok) {
    const errData = (await res.json().catch(() => ({}))) as { error?: string };
    throw new ApiError(errData.error || `Stream request failed (${res.status})`, res.status);
  }

  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('text/event-stream') || !res.body) {
    return (await res.json()) as TResult;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let accumulated = '';
  let finalPayload: TResult | null = null;

  const onAbort = () => {
    void reader.cancel('Stream aborted').catch(() => {});
  };
  options.signal?.addEventListener('abort', onAbort, { once: true });

  const processBlock = (block: string) => {
    const lines = block.split('\n');
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) return;
    const rawData = dataLines.join('\n');
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(rawData) as Record<string, unknown>;
    } catch {
      return;
    }

    if (eventName === 'error') {
      throw new ApiError(String(parsed.error || 'Native stream failed'), 500);
    }
    if (eventName === 'delta' && typeof parsed.delta === 'string') {
      accumulated += parsed.delta;
      options.onDelta?.(accumulated);
    }
    if (eventName === 'done') {
      finalPayload = parsed as unknown as TResult;
    }
  };

  try {
    while (true) {
      if (options.signal?.aborted) {
        throw new DOMException('Stream aborted', 'AbortError');
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 2);
        if (block) processBlock(block);
      }
    }

    const tail = buffer.trim();
    if (tail) processBlock(tail);

    if (!finalPayload) {
      throw new ApiError('Stream ended before completion', 500);
    }
    return finalPayload;
  } finally {
    options.signal?.removeEventListener('abort', onAbort);
    try {
      reader.releaseLock();
    } catch {
      // Lock may already be released after cancel
    }
  }
}
