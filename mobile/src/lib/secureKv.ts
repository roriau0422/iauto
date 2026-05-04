/**
 * Platform-aware secure key-value store.
 *
 * Native (iOS/Android): expo-secure-store — Keychain / EncryptedSharedPreferences.
 * Web: localStorage. Web isn't a supported production target for iAuto, but
 *      Metro's web bundler is what `expo start` opens by default and crashing
 *      on first paint there ruins the dev loop. The web build is "good enough
 *      for layout previews", not a security boundary.
 * SSR / no-window: in-memory map so imports don't blow up.
 */

import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

export type SecureKvOptions = SecureStore.SecureStoreOptions;

const memory = new Map<string, string>();

function webGet(key: string): string | null {
  if (typeof window === 'undefined' || !window.localStorage) return memory.get(key) ?? null;
  return window.localStorage.getItem(key);
}

function webSet(key: string, value: string): void {
  if (typeof window === 'undefined' || !window.localStorage) {
    memory.set(key, value);
    return;
  }
  window.localStorage.setItem(key, value);
}

function webDelete(key: string): void {
  if (typeof window === 'undefined' || !window.localStorage) {
    memory.delete(key);
    return;
  }
  window.localStorage.removeItem(key);
}

export async function getItem(key: string, opts?: SecureKvOptions): Promise<string | null> {
  if (Platform.OS === 'web') return webGet(key);
  return SecureStore.getItemAsync(key, opts);
}

export async function setItem(key: string, value: string, opts?: SecureKvOptions): Promise<void> {
  if (Platform.OS === 'web') {
    webSet(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value, opts);
}

export async function deleteItem(key: string, opts?: SecureKvOptions): Promise<void> {
  if (Platform.OS === 'web') {
    webDelete(key);
    return;
  }
  await SecureStore.deleteItemAsync(key, opts);
}

export const WHEN_UNLOCKED_THIS_DEVICE_ONLY = SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY;
