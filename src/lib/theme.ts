import { useCallback, useEffect, useState } from 'react';

export type ZyrquenTheme = 'dark' | 'light';

const THEME_STORAGE_KEY = 'zyrquen_theme';
const THEME_EVENT = 'zyrquen-theme-change';

export function getStoredTheme(): ZyrquenTheme {
  if (typeof window === 'undefined') return 'dark';
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') {
      return saved;
    }
  } catch {
    // ignore storage access issues
  }
  return document.documentElement.classList.contains('light') ? 'light' : 'dark';
}

export function applyThemeToDocument(theme: ZyrquenTheme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.remove('dark', 'light');
  root.classList.add(theme);
  root.dataset.theme = theme;

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute('content', theme === 'dark' ? '#090E1F' : '#F4F7FF');
  }
}

export function useZyrquenTheme() {
  const [theme, setThemeState] = useState<ZyrquenTheme>(() => getStoredTheme());

  useEffect(() => {
    applyThemeToDocument(theme);
  }, [theme]);

  useEffect(() => {
    const onThemeEvent = (ev: Event) => {
      const detail = (ev as CustomEvent<ZyrquenTheme>).detail;
      if (detail === 'dark' || detail === 'light') {
        setThemeState(detail);
      }
    };
    window.addEventListener(THEME_EVENT, onThemeEvent);
    return () => window.removeEventListener(THEME_EVENT, onThemeEvent);
  }, []);

  const setTheme = useCallback((next: ZyrquenTheme) => {
    setThemeState(next);
    applyThemeToDocument(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // ignore
    }
    window.dispatchEvent(new CustomEvent<ZyrquenTheme>(THEME_EVENT, { detail: next }));
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [setTheme, theme]);

  return { theme, setTheme, toggleTheme };
}
