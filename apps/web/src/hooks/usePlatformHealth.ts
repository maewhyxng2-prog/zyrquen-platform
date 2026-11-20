"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import type { ApiHealth, NativeHealth } from "@/lib/types";

export function usePlatformHealth() {
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null);
  const [nativeHealth, setNativeHealth] = useState<NativeHealth | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [nativeError, setNativeError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const [apiResult, nativeResult] = await Promise.allSettled([
      apiRequest<ApiHealth>("health"),
      apiRequest<NativeHealth>("v1/native-ai/health"),
    ]);

    if (apiResult.status === "fulfilled") {
      setApiHealth(apiResult.value);
      setApiError(null);
    } else {
      setApiError(apiResult.reason instanceof Error ? apiResult.reason.message : "API health is unavailable.");
    }

    if (nativeResult.status === "fulfilled") {
      setNativeHealth(nativeResult.value);
      setNativeError(null);
    } else {
      setNativeError(nativeResult.reason instanceof Error ? nativeResult.reason.message : "Native runtime health is unavailable.");
    }

    setLastChecked(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    const initialCheck = window.setTimeout(() => void refresh(), 0);
    const interval = window.setInterval(() => void refresh(), 30_000);
    return () => {
      window.clearTimeout(initialCheck);
      window.clearInterval(interval);
    };
  }, [refresh]);

  return { apiHealth, nativeHealth, apiError, nativeError, loading, lastChecked, refresh };
}
