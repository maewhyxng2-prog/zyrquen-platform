"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { apiRequest } from "@/lib/api";
import type {
  ApiHealth,
  NativeHealth,
  WorkflowServicesStatus,
} from "@/lib/types";

export type PlatformHealthState = {
  apiHealth: ApiHealth | null;
  nativeHealth: NativeHealth | null;
  workflowServices: WorkflowServicesStatus | null;
  apiError: string | null;
  nativeError: string | null;
  workflowServicesError: string | null;
  loading: boolean;
  lastChecked: Date | null;
  platformVersion: string | null;
  platformStage: string | null;
  modelVersion: string | null;
  refresh: () => Promise<void>;
};

const PlatformHealthContext = createContext<PlatformHealthState | null>(null);

function usePlatformHealthPolling(enabled: boolean): PlatformHealthState {
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null);
  const [nativeHealth, setNativeHealth] = useState<NativeHealth | null>(null);
  const [workflowServices, setWorkflowServices] =
    useState<WorkflowServicesStatus | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [nativeError, setNativeError] = useState<string | null>(null);
  const [workflowServicesError, setWorkflowServicesError] = useState<
    string | null
  >(null);
  const [loading, setLoading] = useState(enabled);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    const currentRequestId = ++requestId.current;

    setLoading(true);

    const [apiResult, nativeResult, workflowServicesResult] =
      await Promise.allSettled([
        apiRequest<ApiHealth>("health"),
        apiRequest<NativeHealth>("v1/native-ai/health"),
        apiRequest<WorkflowServicesStatus>("v1/workflows/services/status"),
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

    if (workflowServicesResult.status === "fulfilled") {
      setWorkflowServices(workflowServicesResult.value);
      setWorkflowServicesError(null);
    } else {
      setWorkflowServices(null);
      setWorkflowServicesError(
        workflowServicesResult.reason instanceof Error
          ? workflowServicesResult.reason.message
          : "ไม่สามารถตรวจสอบสถานะ Workflow Scheduler และ Recovery ได้",
      );
    }

    setLastChecked(new Date());
    setLoading(false);
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;

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
  }, [enabled, refresh]);

  const platformVersion =
    nativeHealth?.platform_version ??
    apiHealth?.native_ai?.platform_version ??
    null;

  const platformStage =
    nativeHealth?.platform_stage ??
    apiHealth?.native_ai?.platform_stage ??
    null;

  const modelVersion =
    nativeHealth?.model_version ??
    apiHealth?.native_ai?.model_version ??
    null;

  return useMemo(
    () => ({
      apiHealth,
      nativeHealth,
      workflowServices,
      apiError,
      nativeError,
      workflowServicesError,
      loading,
      lastChecked,
      platformVersion,
      platformStage,
      modelVersion,
      refresh,
    }),
    [
      apiHealth,
      nativeHealth,
      workflowServices,
      apiError,
      nativeError,
      workflowServicesError,
      loading,
      lastChecked,
      platformVersion,
      platformStage,
      modelVersion,
      refresh,
    ],
  );
}

export function PlatformHealthProvider({ children }: { children: ReactNode }) {
  const value = usePlatformHealthPolling(true);
  return createElement(PlatformHealthContext.Provider, { value }, children);
}

export function usePlatformHealth(): PlatformHealthState {
  const shared = useContext(PlatformHealthContext);
  const standalone = usePlatformHealthPolling(shared === null);
  return shared ?? standalone;
}
