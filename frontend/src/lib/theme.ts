import { useEffect, useState } from 'react';

export type ThemeMode = 'dark' | 'light';

const THEME_QUERY = '(prefers-color-scheme: dark)';

export function resolveSystemTheme(): ThemeMode {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'dark';
  }
  return window.matchMedia(THEME_QUERY).matches ? 'dark' : 'light';
}

export function applyTheme(theme: ThemeMode) {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = theme;
}

let themeSyncStarted = false;

export function ensureSystemThemeSync() {
  if (themeSyncStarted || typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return;
  }

  themeSyncStarted = true;
  const mediaQuery = window.matchMedia(THEME_QUERY);
  const sync = () => applyTheme(mediaQuery.matches ? 'dark' : 'light');

  sync();
  mediaQuery.addEventListener('change', sync);
}

export function useResolvedTheme(): ThemeMode {
  const [theme, setTheme] = useState<ThemeMode>(() => resolveSystemTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }

    const mediaQuery = window.matchMedia(THEME_QUERY);
    const handleChange = () => {
      setTheme(mediaQuery.matches ? 'dark' : 'light');
    };

    handleChange();
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  return theme;
}
