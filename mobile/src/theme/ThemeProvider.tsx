/**
 * Runtime theme + tweaks state. Mirrors the `useTweaks` hook in the
 * design's tweaks-panel.jsx — role / accent / radius / card style.
 *
 * Persisted via expo-secure-store so the user's preferences survive
 * app restart. Tweaks live in a separate key from auth tokens.
 */

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';

import { getItem, setItem } from '../lib/secureKv';

import {
  type AccentKey,
  type CardKey,
  type RadiusKey,
  type Theme,
  type ThemeName,
  buildTheme,
} from './tokens';

const TWEAKS_KEY = 'iauto.tweaks.v1';

type Tweaks = {
  theme: ThemeName | 'system';
  accent: AccentKey;
  radius: RadiusKey;
  card: CardKey;
};

const DEFAULT_TWEAKS: Tweaks = {
  theme: 'system',
  accent: 'blue',
  radius: 'soft',
  card: 'glass',
};

type Ctx = {
  theme: Theme;
  tweaks: Tweaks;
  setTweak: <K extends keyof Tweaks>(k: K, v: Tweaks[K]) => void;
};

const ThemeCtx = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const systemScheme = useColorScheme();
  const [tweaks, setTweaks] = useState<Tweaks>(DEFAULT_TWEAKS);

  // Hydrate persisted tweaks on mount.
  useEffect(() => {
    getItem(TWEAKS_KEY)
      .then((raw) => {
        if (!raw) return;
        try {
          const parsed = JSON.parse(raw) as Partial<Tweaks>;
          setTweaks((cur) => ({ ...cur, ...parsed }));
        } catch {
          // Corrupt stored value — fall back to defaults.
        }
      })
      .catch(() => {
        // SecureStore can fail on some emulator boot states; ignore.
      });
  }, []);

  const themeName: ThemeName = tweaks.theme === 'system' ? (systemScheme === 'light' ? 'light' : 'dark') : tweaks.theme;

  const theme = useMemo(
    () => buildTheme({ themeName, accent: tweaks.accent, radius: tweaks.radius, card: tweaks.card }),
    [themeName, tweaks.accent, tweaks.radius, tweaks.card],
  );

  const setTweak: Ctx['setTweak'] = (k, v) => {
    setTweaks((cur) => {
      const next = { ...cur, [k]: v };
      setItem(TWEAKS_KEY, JSON.stringify(next)).catch(() => undefined);
      return next;
    });
  };

  return <ThemeCtx.Provider value={{ theme, tweaks, setTweak }}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Theme {
  const ctx = useContext(ThemeCtx);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx.theme;
}

export function useTweaks() {
  const ctx = useContext(ThemeCtx);
  if (!ctx) throw new Error('useTweaks must be used inside <ThemeProvider>');
  return { tweaks: ctx.tweaks, setTweak: ctx.setTweak };
}
