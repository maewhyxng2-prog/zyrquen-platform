import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { WifiOff } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { AppShell } from './components/AppShell';
import { AuthGate } from './components/AuthGate';
import { HomeView } from './components/HomeView';

const CommandPalette = lazy(() =>
  import('./components/CommandPalette').then((m) => ({ default: m.CommandPalette }))
);
const MemoryWorkflowsView = lazy(() =>
  import('./components/MemoryWorkflowsView').then((m) => ({ default: m.MemoryWorkflowsView }))
);
const SettingsView = lazy(() =>
  import('./components/SettingsView').then((m) => ({ default: m.SettingsView }))
);
const WorkspaceView = lazy(() =>
  import('./components/WorkspaceView').then((m) => ({ default: m.WorkspaceView }))
);
const ProjectsView = lazy(() =>
  import('./components/IntelligenceWorkspaceViews').then((m) => ({ default: m.ProjectsView }))
);
const MyTasksView = lazy(() =>
  import('./components/IntelligenceWorkspaceViews').then((m) => ({ default: m.MyTasksView }))
);
const CreateArtifactView = lazy(() =>
  import('./components/IntelligenceWorkspaceViews').then((m) => ({ default: m.CreateArtifactView }))
);
const AnalysisView = lazy(() =>
  import('./components/IntelligenceWorkspaceViews').then((m) => ({ default: m.AnalysisView }))
);
const ArtifactsView = lazy(() =>
  import('./components/IntelligenceWorkspaceViews').then((m) => ({ default: m.ArtifactsView }))
);
import type { CreatePresetKind } from './components/IntelligenceWorkspaceViews';
import { apiRequest, ApiError, streamConversationMessage } from './lib/api';
import { useZyrquenTheme } from './lib/theme';
import type {
  AppScreen,
  AuthStatus,
  ClientLatencySample,
  ConversationSummary,
  HomeSummary,
  MemorySnapshot,
  MessageItem,
  ModelVariantId,
  ReasoningMode,
  SettingsTab,
  ThreadCleanupVerification,
  User,
} from './types';
export type { MemorySnapshot, ThreadCleanupVerification } from './types';

function readRouteFromUrl(): {
  screen: AppScreen;
  conversationId: string | null;
  settingsTab: SettingsTab;
  verifyToken: string | null;
  resetToken: string | null;
} {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view');
  const cid = params.get('cid');
  const tab = params.get('tab');
  const verifyToken = params.get('verify_token');
  const resetToken = params.get('reset_token');

  const screen: AppScreen =
    view === 'projects' ||
    view === 'tasks' ||
    view === 'create' ||
    view === 'analysis' ||
    view === 'artifacts' ||
    view === 'workspace' ||
    view === 'memory' ||
    view === 'settings'
      ? view
      : 'overview';
  const settingsTab: SettingsTab =
    tab === 'developer' || tab === 'admin' ? tab : 'account';

  return {
    screen,
    conversationId: cid || null,
    settingsTab,
    verifyToken: verifyToken || null,
    resetToken: resetToken || null,
  };
}

function buildUrl(
  screen: AppScreen,
  conversationId: string | null,
  settingsTab: SettingsTab
): string {
  const params = new URLSearchParams();
  if (screen !== 'overview') {
    params.set('view', screen);
  }
  if (screen === 'workspace' && conversationId) {
    params.set('cid', conversationId);
  }
  if (screen === 'settings' && settingsTab !== 'account') {
    params.set('tab', settingsTab);
  }
  const qs = params.toString();
  const basePath = window.location.pathname === '/login' ? '/' : window.location.pathname;
  return qs ? `${basePath}?${qs}` : basePath;
}

export interface ThreadLoadEntry {
  requestId: number;
  conversationId: string;
  controller: AbortController;
  cleanedUp: boolean;
  settled: boolean;
}

interface BrowserPerformanceMemory {
  usedJSHeapSize: number;
  totalJSHeapSize: number;
  jsHeapSizeLimit: number;
}

const PERF_SAMPLE_LIMIT = 60;
const HEAP_LEAK_THRESHOLD_MB = 48;
const textByteEncoder = typeof TextEncoder !== 'undefined' ? new TextEncoder() : null;

export function verifyThreadEffectCleanup(
  entries: Iterable<ThreadLoadEntry>
): ThreadCleanupVerification {
  const leakedRequestIds: number[] = [];
  let activeCount = 0;
  let abortedCount = 0;

  for (const entry of entries) {
    if (entry.controller.signal.aborted) {
      abortedCount += 1;
    }
    if (!entry.settled && !entry.cleanedUp) {
      activeCount += 1;
    }
    if (entry.cleanedUp && !entry.controller.signal.aborted && !entry.settled) {
      leakedRequestIds.push(entry.requestId);
    }
  }

  return {
    clean: leakedRequestIds.length === 0,
    activeCount,
    abortedCount,
    leakedRequestIds,
    checkedAt: Date.now(),
  };
}

export function readRuntimeMemorySnapshot(params: {
  streamingContent: string | null;
  messageCount: number;
  activeStreamCount: number;
  pendingThreadLoads: number;
  baselineHeapMB: number | null;
}): MemorySnapshot {
  const perf =
    typeof performance !== 'undefined'
      ? (performance as unknown as { memory?: BrowserPerformanceMemory })
      : undefined;
  const mem = perf?.memory;
  const heapSupported = Boolean(
    mem &&
      typeof mem.usedJSHeapSize === 'number' &&
      typeof mem.totalJSHeapSize === 'number' &&
      typeof mem.jsHeapSizeLimit === 'number'
  );

  const toMB = (bytes: number) => Math.round((bytes / (1024 * 1024)) * 100) / 100;
  const usedJSHeapMB = heapSupported && mem ? toMB(mem.usedJSHeapSize) : null;
  const totalJSHeapMB = heapSupported && mem ? toMB(mem.totalJSHeapSize) : null;
  const jsHeapLimitMB = heapSupported && mem ? toMB(mem.jsHeapSizeLimit) : null;
  const heapDeltaMB =
    usedJSHeapMB !== null && params.baselineHeapMB !== null
      ? Math.round((usedJSHeapMB - params.baselineHeapMB) * 100) / 100
      : null;

  const content = params.streamingContent || '';
  const streamBufferBytes = textByteEncoder
    ? textByteEncoder.encode(content).byteLength
    : content.length * 2;

  return {
    timestamp: Date.now(),
    heapSupported,
    usedJSHeapMB,
    totalJSHeapMB,
    jsHeapLimitMB,
    streamBufferBytes,
    messageCount: params.messageCount,
    activeStreamCount: params.activeStreamCount,
    pendingThreadLoads: params.pendingThreadLoads,
    heapDeltaMB,
    leakWarning:
      (heapDeltaMB !== null && heapDeltaMB >= HEAP_LEAK_THRESHOLD_MB) ||
      params.pendingThreadLoads > 1,
  };
}

export interface PerformanceMonitorProps {
  active: boolean;
  streaming: boolean;
  streamingContent: string | null;
  messageCount: number;
  getActiveStreamCount: () => number;
  getPendingThreadLoads: () => number;
  getCleanupVerification?: () => ThreadCleanupVerification | null;
  sampleIntervalMs?: number;
  onSample?: (snapshot: MemorySnapshot) => void;
}

export function PerformanceMonitor({
  active,
  streaming,
  streamingContent,
  messageCount,
  getActiveStreamCount,
  getPendingThreadLoads,
  getCleanupVerification,
  sampleIntervalMs = 1000,
  onSample,
}: PerformanceMonitorProps) {
  const samplesRef = useRef<MemorySnapshot[]>([]);
  const baselineHeapRef = useRef<number | null>(null);
  const latestMetricsRef = useRef({
    streamingContent,
    messageCount,
    getActiveStreamCount,
    getPendingThreadLoads,
    getCleanupVerification,
  });
  const onSampleRef = useRef(onSample);

  useEffect(() => {
    latestMetricsRef.current = {
      streamingContent,
      messageCount,
      getActiveStreamCount,
      getPendingThreadLoads,
      getCleanupVerification,
    };
  }, [
    streamingContent,
    messageCount,
    getActiveStreamCount,
    getPendingThreadLoads,
    getCleanupVerification,
  ]);

  useEffect(() => {
    onSampleRef.current = onSample;
  }, [onSample]);

  const recordSample = useCallback(() => {
    const cur = latestMetricsRef.current;
    const snap = readRuntimeMemorySnapshot({
      streamingContent: cur.streamingContent,
      messageCount: cur.messageCount,
      activeStreamCount: cur.getActiveStreamCount(),
      pendingThreadLoads: cur.getPendingThreadLoads(),
      baselineHeapMB: baselineHeapRef.current,
    });
    if (baselineHeapRef.current === null && snap.usedJSHeapMB !== null) {
      baselineHeapRef.current = snap.usedJSHeapMB;
      snap.heapDeltaMB = 0;
    }

    const nextSamples = [...samplesRef.current, snap];
    if (nextSamples.length > PERF_SAMPLE_LIMIT) {
      nextSamples.splice(0, nextSamples.length - PERF_SAMPLE_LIMIT);
    }
    samplesRef.current = nextSamples;

    if (typeof window !== 'undefined') {
      (
        window as unknown as {
          __ZYRQUEN_PERF_MONITOR__?: {
            active: boolean;
            streaming: boolean;
            latest: MemorySnapshot;
            samplesCount: number;
            cleanupVerification: ThreadCleanupVerification | null;
          };
        }
      ).__ZYRQUEN_PERF_MONITOR__ = {
        active,
        streaming,
        latest: snap,
        samplesCount: nextSamples.length,
        cleanupVerification: cur.getCleanupVerification?.() ?? null,
      };
    }

    onSampleRef.current?.(snap);
  }, [active, streaming]);

  useEffect(() => {
    if (!active) {
      baselineHeapRef.current = null;
      samplesRef.current = [];
      return;
    }

    recordSample();
    if (!streaming) return;

    const timer = window.setInterval(recordSample, Math.max(200, sampleIntervalMs));
    return () => {
      window.clearInterval(timer);
      baselineHeapRef.current = null;
    };
  }, [active, streaming, sampleIntervalMs, recordSample]);

  useEffect(() => {
    if (!active || !streaming) return;
    recordSample();
  }, [active, streaming, streamingContent, recordSample]);

  return null;
}

export default function App() {
  useZyrquenTheme();
  const initialRoute = readRouteFromUrl();

  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [nativeReady, setNativeReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  const [screen, setScreen] = useState<AppScreen>(initialRoute.screen);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>(initialRoute.settingsTab);
  const [verifyToken, setVerifyToken] = useState<string | null>(initialRoute.verifyToken);
  const [resetToken, setResetToken] = useState<string | null>(initialRoute.resetToken);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(
    initialRoute.conversationId
  );

  const [homeSummary, setHomeSummary] = useState<HomeSummary | null>(null);
  const [homeLoading, setHomeLoading] = useState(false);
  const [homeError, setHomeError] = useState<string | null>(null);

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeTitle, setActiveTitle] = useState('เซสชันใหม่');
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [lastFailedPrompt, setLastFailedPrompt] = useState<{
    content: string;
    mode: ReasoningMode;
    attachment?: string;
    modelVariant?: ModelVariantId;
  } | null>(null);

  const [defaultMode, setDefaultMode] = useState<ReasoningMode>('auto');
  const [selectedModelVariant, setSelectedModelVariant] =
    useState<ModelVariantId>('zyrquen-omega-v1');
  const [createPreset, setCreatePreset] = useState<CreatePresetKind>('software');
  const [autoExpandTrace, setAutoExpandTrace] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [isOnline, setIsOnline] = useState<boolean>(() =>
    typeof navigator !== 'undefined' ? navigator.onLine : true
  );
  const [perfSamples, setPerfSamples] = useState<MemorySnapshot[]>([]);
  const [clientLatencies, setClientLatencies] = useState<ClientLatencySample[]>([]);
  const [cleanupVerification, setCleanupVerification] = useState<ThreadCleanupVerification | null>(null);
  const skipNextLoadCidRef = useRef<string | null>(null);
  const activeThreadRequestsRef = useRef<Map<number, ThreadLoadEntry>>(new Map());
  const threadRequestSeqRef = useRef(0);
  const activeStreamControllerRef = useRef<AbortController | null>(null);
  const lastCleanupVerificationRef = useRef<ThreadCleanupVerification | null>(null);
  const baselineHeapRef = useRef<number | null>(null);

  const handlePerfSample = useCallback((snapshot: MemorySnapshot) => {
    setPerfSamples((prev) => {
      const next = [...prev, snapshot];
      return next.length > PERF_SAMPLE_LIMIT ? next.slice(next.length - PERF_SAMPLE_LIMIT) : next;
    });
    if (lastCleanupVerificationRef.current) {
      setCleanupVerification(lastCleanupVerificationRef.current);
    }
  }, []);

  const handleCapturePerfSampleNow = useCallback(() => {
    const snap = readRuntimeMemorySnapshot({
      streamingContent,
      messageCount: messages.length,
      activeStreamCount: activeStreamControllerRef.current ? 1 : 0,
      pendingThreadLoads: activeThreadRequestsRef.current.size,
      baselineHeapMB: baselineHeapRef.current,
    });
    if (baselineHeapRef.current === null && snap.usedJSHeapMB !== null) {
      baselineHeapRef.current = snap.usedJSHeapMB;
      snap.heapDeltaMB = 0;
    }
    handlePerfSample(snap);
  }, [handlePerfSample, messages.length, streamingContent]);

  const pushRoute = useCallback(
    (nextScreen: AppScreen, nextCid: string | null = null, nextTab: SettingsTab = 'account') => {
      const targetUrl = buildUrl(nextScreen, nextCid, nextTab);
      if (window.location.pathname + window.location.search !== targetUrl) {
        window.history.pushState(
          { screen: nextScreen, conversationId: nextCid, settingsTab: nextTab },
          '',
          targetUrl
        );
      }
      setScreen(nextScreen);
      setActiveConversationId(nextCid);
      setSettingsTab(nextTab);
    },
    []
  );

  useEffect(() => {
    const onPopState = () => {
      const parsed = readRouteFromUrl();
      setScreen(parsed.screen);
      setActiveConversationId(parsed.conversationId);
      setSettingsTab(parsed.settingsTab);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const bootstrapAuthAndHealth = useCallback(async () => {
    setConnectionError(null);
    try {
      const [status, health, meRes] = await Promise.all([
        apiRequest<AuthStatus>('/api/auth/status'),
        apiRequest<{ ok: boolean; nativeCore: string }>('/api/health').catch(() => ({
          ok: false,
          nativeCore: 'offline',
        })),
        apiRequest<{ user: User }>('/api/auth/me').catch(() => null),
      ]);
      setAuthStatus(status);
      setNativeReady(health.ok && health.nativeCore === 'ready');
      if (meRes?.user) {
        setUser(meRes.user);
        setToken((prev) => prev || '__cookie__');
      }
    } catch (err) {
      setNativeReady(false);
      setConnectionError(
        err instanceof ApiError
          ? err.message
          : 'ไม่สามารถเชื่อมต่อกับ ZYRQUEN Cloud Core ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต'
      );
    }
  }, []);

  useEffect(() => {
    const onOnline = () => {
      setIsOnline(true);
      void bootstrapAuthAndHealth();
    };
    const onOffline = () => {
      setIsOnline(false);
      setNativeReady(false);
    };
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, [bootstrapAuthAndHealth]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active && isOnline) void bootstrapAuthAndHealth();
    });
    return () => {
      active = false;
    };
  }, [bootstrapAuthAndHealth, isOnline]);

  const loadHomeAndConversations = useCallback(async () => {
    if (!token) return;
    await Promise.resolve();
    setHomeLoading(true);
    setHomeError(null);
    try {
      const [summary, convList] = await Promise.all([
        apiRequest<HomeSummary>('/api/home', { token }),
        apiRequest<{ conversations: ConversationSummary[] }>('/api/conversations', { token }),
      ]);
      setHomeSummary(summary);
      setConversations(convList.conversations);
    } catch (err) {
      setHomeError(err instanceof ApiError ? err.message : 'Unable to load workspace summary');
    } finally {
      setHomeLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token || !user) return;
    let active = true;
    Promise.resolve().then(() => {
      if (active) void loadHomeAndConversations();
    });
    return () => {
      active = false;
    };
  }, [loadHomeAndConversations, token, user]);

  useEffect(() => {
    if (!token || !user || !verifyToken) return;
    let active = true;
    apiRequest<{ ok: boolean; user?: User }>('/api/auth/verify-email', {
      method: 'POST',
      token,
      body: { token: verifyToken },
    })
      .then((res) => {
        if (!active) return;
        if (res.ok && res.user) {
          setUser(res.user);
        }
        setVerifyToken(null);
        const cleanUrl = buildUrl(screen, activeConversationId, settingsTab);
        window.history.replaceState(
          { screen, conversationId: activeConversationId, settingsTab },
          '',
          cleanUrl
        );
      })
      .catch(() => {
        if (active) setVerifyToken(null);
      });
    return () => {
      active = false;
    };
  }, [activeConversationId, screen, settingsTab, token, user, verifyToken]);

  useEffect(() => {
    if (!token || !user) return;
    if (window.location.pathname === '/login') {
      const targetUrl = buildUrl(screen, activeConversationId, settingsTab);
      window.history.replaceState(
        { screen, conversationId: activeConversationId, settingsTab },
        '',
        targetUrl
      );
    }
  }, [activeConversationId, screen, settingsTab, token, user]);

  const loadConversationThread = useCallback(
    async (
      cid: string,
      options?: {
        signal?: AbortSignal;
        isActive?: () => boolean;
      }
    ) => {
      if (!token) return;
      const controller = new AbortController();
      const requestId = ++threadRequestSeqRef.current;
      const entry: ThreadLoadEntry = {
        requestId,
        conversationId: cid,
        controller,
        cleanedUp: false,
        settled: false,
      };
      activeThreadRequestsRef.current.set(requestId, entry);

      const onExternalAbort = () => {
        entry.cleanedUp = true;
        controller.abort();
      };
      if (options?.signal) {
        if (options.signal.aborted) {
          onExternalAbort();
        } else {
          options.signal.addEventListener('abort', onExternalAbort, { once: true });
        }
      }

      const canCommit = () =>
        !controller.signal.aborted && (!options?.isActive || options.isActive());

      await Promise.resolve();
      if (!canCommit()) {
        entry.settled = true;
        activeThreadRequestsRef.current.delete(requestId);
        options?.signal?.removeEventListener('abort', onExternalAbort);
        return;
      }

      setLoadingThread(true);
      setWorkspaceError(null);
      try {
        const res = await apiRequest<{
          conversation: ConversationSummary;
          messages: MessageItem[];
        }>(`/api/conversations/${cid}`, {
          token,
          signal: controller.signal,
        });
        if (!canCommit()) return;
        setActiveTitle(res.conversation.title);
        setMessages(res.messages);
      } catch (err) {
        if (controller.signal.aborted || (err instanceof Error && err.name === 'AbortError')) {
          return;
        }
        if (canCommit()) {
          if (err instanceof ApiError && err.status === 404) {
            // Stale or deleted conversation ID: cleanly reset to a fresh session without surfacing "Conversation not found"
            setActiveConversationId(null);
            setActiveTitle('เซสชันใหม่');
            setMessages([]);
            setWorkspaceError(null);
            const cleanUrl = buildUrl('workspace', null, settingsTab);
            if (window.location.pathname + window.location.search !== cleanUrl) {
              window.history.replaceState(
                { screen: 'workspace', conversationId: null, settingsTab },
                '',
                cleanUrl
              );
            }
            void loadHomeAndConversations();
          } else {
            setWorkspaceError(err instanceof ApiError ? err.message : 'Failed to load conversation');
          }
        }
      } finally {
        entry.settled = true;
        activeThreadRequestsRef.current.delete(requestId);
        options?.signal?.removeEventListener('abort', onExternalAbort);
        if (canCommit()) {
          setLoadingThread(false);
        }
      }
    },
    [loadHomeAndConversations, settingsTab, token]
  );

  useEffect(() => {
    if (!token || screen !== 'workspace' || !activeConversationId) return;
    if (skipNextLoadCidRef.current === activeConversationId) {
      skipNextLoadCidRef.current = null;
      return;
    }

    let active = true;
    const cid = activeConversationId;
    const controller = new AbortController();
    const threadRequests = activeThreadRequestsRef.current;

    Promise.resolve().then(() => {
      if (active && !controller.signal.aborted) {
        void loadConversationThread(cid, {
          signal: controller.signal,
          isActive: () => active,
        });
      }
    });

    return () => {
      active = false;
      controller.abort();
      for (const entry of threadRequests.values()) {
        if (entry.conversationId === cid && !entry.settled) {
          entry.cleanedUp = true;
          entry.controller.abort();
        }
      }
      const verification = verifyThreadEffectCleanup(threadRequests.values());
      lastCleanupVerificationRef.current = verification;
      if (typeof window !== 'undefined') {
        const win = window as unknown as {
          __ZYRQUEN_PERF_MONITOR__?: { cleanupVerification?: ThreadCleanupVerification | null };
        };
        if (win.__ZYRQUEN_PERF_MONITOR__) {
          win.__ZYRQUEN_PERF_MONITOR__.cleanupVerification = verification;
        }
      }
      for (const [reqId, entry] of threadRequests.entries()) {
        if (entry.settled || entry.controller.signal.aborted) {
          threadRequests.delete(reqId);
        }
      }
    };
  }, [activeConversationId, loadConversationThread, screen, token]);

  async function handleStartPrompt(prompt: string, mode: ReasoningMode, attachment?: string) {
    if (!token) return;
    setWorkspaceError(null);
    const titleSeed = prompt.trim() || (attachment ? 'วิเคราะห์เอกสารที่แนบ' : 'งานใหม่');
    try {
      const created = await apiRequest<{ conversation: ConversationSummary }>('/api/conversations', {
        method: 'POST',
        token,
        body: { title: titleSeed.slice(0, 48), mode },
      });
      const cid = created.conversation.id;
      skipNextLoadCidRef.current = cid;
      setConversations((prev) => [
        { ...created.conversation, message_count: 0 },
        ...prev,
      ]);
      setActiveTitle(created.conversation.title);
      setMessages([]);
      pushRoute('workspace', cid, settingsTab);
      await sendMessageToConversation(cid, prompt, mode, attachment, selectedModelVariant);
    } catch (err) {
      setWorkspaceError(err instanceof ApiError ? err.message : 'Failed to start task');
    }
  }

  async function handleCreateProject(title: string, initialPrompt?: string) {
    if (!token) return;
    setWorkspaceError(null);
    const created = await apiRequest<{ conversation: ConversationSummary }>('/api/conversations', {
      method: 'POST',
      token,
      body: { title: title.slice(0, 80), mode: defaultMode },
    });
    const cid = created.conversation.id;
    skipNextLoadCidRef.current = cid;
    setConversations((prev) => [
      { ...created.conversation, message_count: 0 },
      ...prev,
    ]);
    setActiveTitle(created.conversation.title);
    setMessages([]);
    pushRoute('workspace', cid, settingsTab);
    if (initialPrompt && initialPrompt.trim()) {
      await sendMessageToConversation(cid, initialPrompt.trim(), defaultMode, undefined, selectedModelVariant);
    } else {
      void loadHomeAndConversations();
    }
  }

  async function sendMessageToConversation(
    cid: string | null,
    content: string,
    mode: ReasoningMode,
    attachment?: string,
    modelVariant: ModelVariantId = selectedModelVariant
  ) {
    if (!token) return;
    activeStreamControllerRef.current?.abort();
    const streamController = new AbortController();
    activeStreamControllerRef.current = streamController;

    setSending(true);
    setStreamingContent(null);
    setWorkspaceError(null);
    setLastFailedPrompt(null);

    try {
      const createFreshConversation = async () => {
        const created = await apiRequest<{ conversation: ConversationSummary }>('/api/conversations', {
          method: 'POST',
          token,
          signal: streamController.signal,
          body: { title: content ? content.slice(0, 48) : 'Attached Context', mode },
        });
        const newCid = created.conversation.id;
        skipNextLoadCidRef.current = newCid;
        setConversations((prev) => [
          { ...created.conversation, message_count: 0 },
          ...prev.filter((c) => c.id !== newCid),
        ]);
        setActiveTitle(created.conversation.title);
        pushRoute('workspace', newCid, settingsTab);
        return newCid;
      };

      let targetCid = cid;
      if (!targetCid) {
        targetCid = await createFreshConversation();
      }

      const requestStart = typeof performance !== 'undefined' ? performance.now() : Date.now();
      let res: {
        title: string;
        user_message: MessageItem;
        assistant_message: MessageItem;
      };
      try {
        res = await streamConversationMessage<{
          title: string;
          user_message: MessageItem;
          assistant_message: MessageItem;
        }>(targetCid, {
          token,
          content,
          mode,
          attachment,
          modelVariant,
          signal: streamController.signal,
          onDelta: (partial) => {
            if (!streamController.signal.aborted) {
              setStreamingContent(partial);
            }
          },
        });
      } catch (streamErr) {
        if (streamErr instanceof ApiError && streamErr.status === 404 && !streamController.signal.aborted) {
          // Recover automatically if targetCid no longer exists in database
          targetCid = await createFreshConversation();
          res = await streamConversationMessage<{
            title: string;
            user_message: MessageItem;
            assistant_message: MessageItem;
          }>(targetCid, {
            token,
            content,
            mode,
            attachment,
            modelVariant,
            signal: streamController.signal,
            onDelta: (partial) => {
              if (!streamController.signal.aborted) {
                setStreamingContent(partial);
              }
            },
          });
        } else {
          throw streamErr;
        }
      }

      if (streamController.signal.aborted) return;
      const elapsedMs =
        Math.round(
          ((typeof performance !== 'undefined' ? performance.now() : Date.now()) - requestStart) *
            100
        ) / 100;
      setClientLatencies((prev) => {
        const next: ClientLatencySample[] = [
          ...prev,
          {
            timestamp: Date.now(),
            label: (content || 'attachment').slice(0, 28),
            endpoint: `/api/conversations/${targetCid}/stream`,
            latencyMs: elapsedMs,
            status: res.assistant_message.status,
          },
        ];
        return next.length > 40 ? next.slice(next.length - 40) : next;
      });
      setActiveTitle(res.title);
      setNativeReady(true);
      setMessages((prev) => [...prev, res.user_message, res.assistant_message]);
      void loadHomeAndConversations();
    } catch (err) {
      if (streamController.signal.aborted || (err instanceof Error && err.name === 'AbortError')) {
        return;
      }
      if (err instanceof ApiError && err.status === 0) {
        setNativeReady(false);
      }
      setLastFailedPrompt({ content, mode, attachment, modelVariant });
      setWorkspaceError(err instanceof ApiError ? err.message : 'Native inference failed');
    } finally {
      if (activeStreamControllerRef.current === streamController) {
        activeStreamControllerRef.current = null;
        setSending(false);
        setStreamingContent(null);
      }
    }
  }

  useEffect(() => {
    const threadRequests = activeThreadRequestsRef.current;
    return () => {
      activeStreamControllerRef.current?.abort();
      activeStreamControllerRef.current = null;
      for (const entry of threadRequests.values()) {
        entry.cleanedUp = true;
        entry.controller.abort();
      }
      threadRequests.clear();
    };
  }, []);

  const handleCancelSending = useCallback(() => {
    activeStreamControllerRef.current?.abort();
    activeStreamControllerRef.current = null;
    setSending(false);
    setStreamingContent(null);
  }, []);

  const handleNewConversation = useCallback(() => {
    activeStreamControllerRef.current?.abort();
    activeStreamControllerRef.current = null;
    setActiveTitle('เซสชันใหม่');
    setMessages([]);
    setWorkspaceError(null);
    pushRoute('workspace', null, settingsTab);
  }, [pushRoute, settingsTab]);

  useEffect(() => {
    if (!token || !user) return;
    const onGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
        return;
      }
      if (e.altKey && !e.ctrlKey && !e.metaKey) {
        if (e.key === '1') {
          e.preventDefault();
          pushRoute('overview', null, settingsTab);
        } else if (e.key === '2') {
          e.preventDefault();
          pushRoute('projects', null, settingsTab);
        } else if (e.key === '3') {
          e.preventDefault();
          pushRoute('tasks', null, settingsTab);
        } else if (e.key === '4') {
          e.preventDefault();
          pushRoute('create', null, settingsTab);
        } else if (e.key === '5') {
          e.preventDefault();
          pushRoute('analysis', null, settingsTab);
        } else if (e.key === '6') {
          e.preventDefault();
          pushRoute('artifacts', null, settingsTab);
        } else if (e.key.toLowerCase() === 'n') {
          e.preventDefault();
          handleNewConversation();
        }
      }
    };
    window.addEventListener('keydown', onGlobalKeyDown);
    return () => window.removeEventListener('keydown', onGlobalKeyDown);
  }, [handleNewConversation, pushRoute, settingsTab, token, user]);

  async function handleDeleteConversation(cid: string) {
    if (!token) return;
    try {
      await apiRequest(`/api/conversations/${cid}`, { method: 'DELETE', token });
      setConversations((prev) => prev.filter((c) => c.id !== cid));
      if (activeConversationId === cid) {
        setActiveTitle('เซสชันใหม่');
        setMessages([]);
        pushRoute('workspace', null, settingsTab);
      }
      void loadHomeAndConversations();
    } catch (err) {
      setWorkspaceError(err instanceof ApiError ? err.message : 'ลบโปรเจกต์ไม่สำเร็จ');
    }
  }

  async function handleLogout() {
    activeStreamControllerRef.current?.abort();
    activeStreamControllerRef.current = null;
    for (const entry of activeThreadRequestsRef.current.values()) {
      entry.cleanedUp = true;
      entry.controller.abort();
    }
    activeThreadRequestsRef.current.clear();
    if (token) {
      await apiRequest('/api/auth/logout', { method: 'POST', token }).catch(() => {});
    }
    setToken(null);
    setUser(null);
    setHomeSummary(null);
    setConversations([]);
    setMessages([]);
    pushRoute('overview', null, 'account');
    void bootstrapAuthAndHealth();
  }

  const isCoreProcessing = Boolean(sending || streamingContent !== null || loadingThread || homeLoading);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.zyrquenProcessing = isCoreProcessing ? 'true' : 'false';
    const logos = document.querySelectorAll<SVGElement>('svg.zyrq-emblem-root');
    logos.forEach((logo) => {
      logo.dataset.processing = isCoreProcessing ? 'true' : 'false';
      logo.classList.toggle('zyrq-emblem-active', isCoreProcessing);
    });
    return () => {
      document.documentElement.dataset.zyrquenProcessing = 'false';
    };
  }, [isCoreProcessing, screen]);

  if (!isOnline) {
    return (
      <div
        role="alert"
        className="flex min-h-[100dvh] flex-col items-center justify-center bg-[var(--color-bg)] px-6 text-center text-[var(--color-text)]"
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]">
          <WifiOff className="h-6 w-6" />
        </div>
        <h2 className="mt-4 text-xl font-bold tracking-tight text-[var(--color-text)]">
          ต้องเชื่อมต่ออินเทอร์เน็ตเท่านั้น
        </h2>
        <p className="mt-2 max-w-sm text-sm text-[var(--color-text-secondary)]">
          ZYRQUEN Ω∞ ไม่รองรับการทำงานแบบออฟไลน์ กรุณาเชื่อมต่ออินเทอร์เน็ตเพื่อเข้าถึงแกนสมองและฐานข้อมูลบนเซิร์ฟเวอร์
        </p>
        <button
          type="button"
          onClick={() => {
            const nowOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;
            setIsOnline(nowOnline);
            if (nowOnline) void bootstrapAuthAndHealth();
          }}
          className="mt-6 flex h-11 items-center justify-center rounded-xl bg-[var(--color-primary)] px-5 text-sm font-medium text-white hover:bg-[var(--color-primary-hover)]"
        >
          ตรวจสอบการเชื่อมต่ออีกครั้ง
        </button>
      </div>
    );
  }

  if (!authStatus) {
    if (connectionError) {
      return (
        <div
          role="alert"
          className="flex min-h-[100dvh] flex-col items-center justify-center bg-[var(--color-bg)] px-6 text-center text-[var(--color-text)]"
        >
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] text-[var(--color-warning)]">
            <WifiOff className="h-6 w-6" />
          </div>
          <h2 className="mt-4 text-xl font-bold tracking-tight text-[var(--color-text)]">
            ไม่สามารถเชื่อมต่อกับระบบออนไลน์ได้
          </h2>
          <p className="mt-2 max-w-sm text-sm text-[var(--color-text-secondary)]">{connectionError}</p>
          <button
            type="button"
            onClick={() => void bootstrapAuthAndHealth()}
            className="mt-6 flex h-11 items-center justify-center rounded-xl bg-[var(--color-primary)] px-5 text-sm font-medium text-white hover:bg-[var(--color-primary-hover)]"
          >
            เชื่อมต่อใหม่อีกครั้ง
          </button>
        </div>
      );
    }
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--color-bg)] text-sm text-[var(--color-text-secondary)]">
        กำลังเริ่มต้นแกนสมอง ZYRQUEN Ω∞...
      </div>
    );
  }

  if (!token || !user) {
    return (
      <AuthGate
        authStatus={authStatus}
        initialVerifyToken={verifyToken}
        initialResetToken={resetToken}
        onClearActionTokens={() => {
          setVerifyToken(null);
          setResetToken(null);
          const cleanUrl = buildUrl(screen, activeConversationId, settingsTab);
          window.history.replaceState(
            { screen, conversationId: activeConversationId, settingsTab },
            '',
            cleanUrl
          );
        }}
        onAuthenticated={(newToken, authedUser) => {
          setToken(newToken);
          setUser(authedUser);
          setAuthStatus((prev) => (prev ? { ...prev, initialized: true } : prev));
          if (window.location.pathname === '/login') {
            const targetUrl = buildUrl(screen, activeConversationId, settingsTab);
            window.history.replaceState(
              { screen, conversationId: activeConversationId, settingsTab },
              '',
              targetUrl
            );
          }
        }}
      />
    );
  }

  const screenTitle =
    screen === 'overview'
      ? 'ภาพรวม'
      : screen === 'projects'
        ? 'โปรเจกต์'
        : screen === 'tasks'
          ? 'งานของฉัน'
          : screen === 'create'
            ? 'สร้างงาน'
            : screen === 'analysis'
              ? 'วิเคราะห์'
              : screen === 'artifacts'
                ? 'คลังผลงาน'
                : screen === 'workspace'
                  ? activeTitle
                  : screen === 'memory'
                    ? 'ความรู้และ Workflow'
                    : settingsTab === 'developer'
                      ? 'โมเดลและการฝึก'
                      : settingsTab === 'admin'
                        ? 'สิทธิ์และความปลอดภัย'
                        : 'ตั้งค่า';

  return (
    <AppShell
      activeScreen={screen}
      activeSettingsTab={user.role !== 'admin' && settingsTab === 'admin' ? 'account' : settingsTab}
      screenTitle={screenTitle}
      user={user}
      showBackOnMobile={
        screen === 'workspace' ||
        screen === 'memory' ||
        (screen === 'settings' && settingsTab !== 'account')
      }
      hideBottomBarOnMobile={screen === 'workspace'}
      isProcessing={isCoreProcessing}
      onNavigate={(next, nextTab) => {
        if (next === 'settings') {
          const safeTab: SettingsTab =
            nextTab === 'admin' && user.role !== 'admin' ? 'account' : nextTab || 'account';
          pushRoute('settings', null, safeTab);
        } else if (next === 'workspace') {
          pushRoute('workspace', activeConversationId, settingsTab);
        } else {
          pushRoute(next, null, settingsTab);
        }
      }}
      onBack={() => {
        if (window.history.length > 1) {
          window.history.back();
        } else {
          pushRoute('overview', null, 'account');
        }
      }}
      onOpenProfile={() => pushRoute('settings', null, 'account')}
      onOpenCommandPalette={() => setPaletteOpen(true)}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={`${screen}-${screen === 'settings' ? settingsTab : ''}`}
          className="flex min-h-0 flex-1 flex-col"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.14, ease: [0.16, 1, 0.3, 1] }}
        >
          {screen === 'overview' && (
            <HomeView
              token={token}
              user={user}
              homeSummary={homeSummary}
              nativeReady={nativeReady}
              loading={homeLoading}
              error={homeError}
              onStartPrompt={(prompt, mode, attachment) =>
                void handleStartPrompt(prompt, mode, attachment)
              }
              onOpenConversation={(cid) => pushRoute('workspace', cid, settingsTab)}
              onOpenAccountSettings={() => pushRoute('settings', null, 'account')}
              onNavigate={(next, options) => {
                if (next === 'create' && options?.preset) {
                  const preset = options.preset;
                  if (
                    preset === 'software' ||
                    preset === 'document' ||
                    preset === 'data' ||
                    preset === 'direct_file'
                  ) {
                    setCreatePreset(preset);
                  }
                }
                pushRoute(next, null, settingsTab);
              }}
              onRetry={() => void loadHomeAndConversations()}
            />
          )}

          {(screen === 'workspace' || (screen === 'settings' && settingsTab === 'admin' && user.role === 'admin')) && (
            <PerformanceMonitor
              active={screen === 'workspace' || (screen === 'settings' && settingsTab === 'admin' && user.role === 'admin')}
              streaming={sending || streamingContent !== null}
              streamingContent={streamingContent}
              messageCount={messages.length}
              getActiveStreamCount={() => (activeStreamControllerRef.current ? 1 : 0)}
              getPendingThreadLoads={() => activeThreadRequestsRef.current.size}
              getCleanupVerification={() => lastCleanupVerificationRef.current}
              onSample={handlePerfSample}
            />
          )}

          <Suspense
            fallback={
              <div className="py-12 text-center text-sm text-[var(--color-text-muted)]">
                กำลังโหลด...
              </div>
            }
          >
            {screen === 'projects' && (
              <ProjectsView
                token={token}
                conversations={conversations}
                onOpenConversation={(cid) => pushRoute('workspace', cid, settingsTab)}
                onCreateProject={handleCreateProject}
                onDeleteProject={handleDeleteConversation}
                onNavigate={(next) => pushRoute(next, null, settingsTab)}
              />
            )}

            {screen === 'tasks' && (
              <MyTasksView
                token={token}
                user={user}
                conversations={conversations}
                onOpenConversation={(cid) => pushRoute('workspace', cid, settingsTab)}
                onNavigate={(next) => pushRoute(next, null, settingsTab)}
              />
            )}

            {screen === 'create' && (
              <CreateArtifactView
                token={token}
                initialKind={createPreset}
                onStartTask={handleStartPrompt}
                onNavigate={(next) => pushRoute(next, null, settingsTab)}
              />
            )}

            {screen === 'analysis' && (
              <AnalysisView
                token={token}
                user={user}
                onStartTask={handleStartPrompt}
                onNavigate={(next) => pushRoute(next, null, settingsTab)}
              />
            )}

            {screen === 'artifacts' && (
              <ArtifactsView
                token={token}
                onOpenConversation={(cid) => pushRoute('workspace', cid, settingsTab)}
                onNavigate={(next) => pushRoute(next, null, settingsTab)}
              />
            )}

            {screen === 'workspace' && (
              <WorkspaceView
                token={token}
                userRole={user.role}
                conversations={conversations}
                activeConversationId={activeConversationId}
                activeTitle={activeTitle}
                messages={messages}
                loadingThread={loadingThread}
                sending={sending}
                streamingContent={streamingContent}
                error={workspaceError}
                defaultMode={defaultMode}
                defaultModelVariant={selectedModelVariant}
                onSelectConversation={(cid) => {
                  if (cid !== activeConversationId) {
                    activeStreamControllerRef.current?.abort();
                    activeStreamControllerRef.current = null;
                  }
                  pushRoute('workspace', cid, settingsTab);
                }}
                onNewConversation={() => void handleNewConversation()}
                onDeleteConversation={(cid) => void handleDeleteConversation(cid)}
                onSendMessage={(content, mode, attachment, variant) =>
                  sendMessageToConversation(
                    activeConversationId,
                    content,
                    mode,
                    attachment,
                    variant || selectedModelVariant
                  )
                }
                onRefreshConversation={async () => {
                  await Promise.all([
                    activeConversationId ? loadConversationThread(activeConversationId) : Promise.resolve(),
                    loadHomeAndConversations(),
                  ]);
                }}
                onRetryLast={
                  lastFailedPrompt
                    ? () =>
                        void sendMessageToConversation(
                          activeConversationId,
                          lastFailedPrompt.content,
                          lastFailedPrompt.mode,
                          lastFailedPrompt.attachment,
                          lastFailedPrompt.modelVariant || selectedModelVariant
                        )
                    : undefined
                }
                onCancelSending={handleCancelSending}
              />
            )}

            {screen === 'memory' && <MemoryWorkflowsView token={token} user={user} />}

            {screen === 'settings' && (
              <SettingsView
                token={token}
                user={user}
                activeTab={user.role !== 'admin' && settingsTab === 'admin' ? 'account' : settingsTab}
                autoExpandTrace={autoExpandTrace}
                defaultMode={defaultMode}
                selectedModelVariant={selectedModelVariant}
                perfSamples={perfSamples}
                clientLatencies={clientLatencies}
                cleanupVerification={cleanupVerification}
                onCapturePerfSample={handleCapturePerfSampleNow}
                onChangeTab={(nextTab) => pushRoute('settings', null, nextTab)}
                onOpenMemory={() => pushRoute('memory', null, 'account')}
                onUserUpdated={(updatedUser) => setUser(updatedUser)}
                onUpdatePreferences={(prefs) => {
                  if (prefs.autoExpandTrace !== undefined) setAutoExpandTrace(prefs.autoExpandTrace);
                  if (prefs.defaultMode !== undefined) setDefaultMode(prefs.defaultMode);
                  if (prefs.modelVariant !== undefined) setSelectedModelVariant(prefs.modelVariant);
                }}
                onLogout={() => void handleLogout()}
              />
            )}
          </Suspense>
        </motion.div>
      </AnimatePresence>

      {paletteOpen && (
        <Suspense fallback={null}>
          <CommandPalette
            open={paletteOpen}
            user={user}
            conversations={conversations}
            onClose={() => setPaletteOpen(false)}
            onNavigate={(nextScreen, nextTab) => {
              if (nextScreen === 'settings') {
                pushRoute('settings', null, nextTab || 'account');
              } else if (nextScreen === 'workspace') {
                pushRoute('workspace', activeConversationId, settingsTab);
              } else {
                pushRoute(nextScreen, null, settingsTab);
              }
            }}
            onNewConversation={handleNewConversation}
            onOpenConversation={(cid) => pushRoute('workspace', cid, settingsTab)}
          />
        </Suspense>
      )}
    </AppShell>
  );
}
