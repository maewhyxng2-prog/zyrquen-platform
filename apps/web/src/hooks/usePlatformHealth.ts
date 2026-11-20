"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";
import type { ApiHealth, NativeHealth } from "@/lib/types";

export function usePlatformHealth() {
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null);
  const [nativeHealth, setNativeHealth] = useState<NativeHealth | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [nativeError, setNativeError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    const currentRequestId = ++requestId.current;

    setLoading(true);

    const [apiResult, nativeResult] = await Promise.allSettled([
      apiRequest<ApiHealth>("health"),
      apiRequest<NativeHealth>("v1/native-ai/health"),
    ]);

    // ป้องกันผลลัพธ์จากคำขอเก่าเขียนทับข้อมูลล่าสุด
    if (currentRequestId !== requestId.current) {
      return;
    }

    if (apiResult.status === "fulfilled") {
      if (apiResult.value?.service !== "zyrquen-api") {
        setApiHealth(null);
        setApiError(
          "ปลายทางพอร์ตที่เชื่อมต่ออยู่ไม่ใช่บริการ ZYRQUEN API กรุณาตรวจสอบค่า ZYRQUEN_API_BASE_URL",
        );
      } else {
        setApiHealth(apiResult.value);
        setApiError(null);
      }
    } else {
      setApiHealth(null);
      setApiError(
        apiResult.reason instanceof Error
          ? apiResult.reason.message
          : "ไม่สามารถตรวจสอบสถานะการเชื่อมต่อ API ได้",
      );
    }

    if (nativeResult.status === "fulfilled") {
      setNativeHealth(nativeResult.value);
      setNativeError(null);
    } else {
      setNativeHealth(null);
      setNativeError(
        nativeResult.reason instanceof Error
          ? nativeResult.reason.message
          : "ไม่สามารถตรวจสอบความพร้อมของ Native Model ได้",
      );
    }

    setLastChecked(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    const initialCheck = window.setTimeout(() => {
      void refresh();
    }, 0);

    const interval = window.setInterval(() => {
      void refresh();
    }, 30_000);

    return () => {
      window.clearTimeout(initialCheck);
      window.clearInterval(interval);
      requestId.current += 1;
    };
  }, [refresh]);

  return {
    apiHealth,
    nativeHealth,
    apiError,
    nativeError,
    loading,
    lastChecked,
    refresh,
  };
}
