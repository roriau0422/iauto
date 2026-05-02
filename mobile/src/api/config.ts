/**
 * Resolves the backend base URL.
 *
 * Dev defaults are wired in `app.json#expo.extra` so dev-client builds
 * work out-of-the-box on simulator / emulator (Android `10.0.2.2` →
 * host loopback, iOS simulator `localhost` works directly).
 *
 * Override in production via EAS env or a `.env.local` consumed by
 * Expo's typed env once we ship a real backend domain.
 */

import Constants from 'expo-constants';
import { Platform } from 'react-native';

type Extra = {
  apiBaseUrl?: string;
  apiBaseUrlIos?: string;
};

export function resolveApiBaseUrl(): string {
  const extra = (Constants.expoConfig?.extra ?? {}) as Extra;
  const fromEnv = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (fromEnv) return fromEnv;
  if (Platform.OS === 'ios' && extra.apiBaseUrlIos) return extra.apiBaseUrlIos;
  if (extra.apiBaseUrl) return extra.apiBaseUrl;
  return 'http://localhost:8000';
}

export const API_BASE_URL = resolveApiBaseUrl();
