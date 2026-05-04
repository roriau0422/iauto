/**
 * Token persistence — JWT access + refresh in SecureStore.
 *
 * SecureStore uses Keychain on iOS, EncryptedSharedPreferences on
 * Android. Tokens are accessible only while the device is unlocked
 * (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`) so iCloud-synced backups can't
 * exfiltrate them.
 *
 * Refresh-token reuse-detection is enforced server-side (a revoked
 * token presented again revokes the entire device chain), so we
 * don't need additional client-side tracking.
 */

import {
  WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  deleteItem,
  getItem,
  setItem,
  type SecureKvOptions,
} from '../lib/secureKv';

const ACCESS_KEY = 'iauto.tok.access';
const REFRESH_KEY = 'iauto.tok.refresh';
const ROLE_KEY = 'iauto.user.role';

const STORE_OPTS: SecureKvOptions = {
  keychainAccessible: WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export type TokenPair = { access: string; refresh: string };

export async function loadTokens(): Promise<TokenPair | null> {
  const [access, refresh] = await Promise.all([
    getItem(ACCESS_KEY, STORE_OPTS),
    getItem(REFRESH_KEY, STORE_OPTS),
  ]);
  if (!access || !refresh) return null;
  return { access, refresh };
}

export async function saveTokens(tokens: TokenPair): Promise<void> {
  await Promise.all([
    setItem(ACCESS_KEY, tokens.access, STORE_OPTS),
    setItem(REFRESH_KEY, tokens.refresh, STORE_OPTS),
  ]);
}

export async function clearTokens(): Promise<void> {
  await Promise.all([
    deleteItem(ACCESS_KEY, STORE_OPTS),
    deleteItem(REFRESH_KEY, STORE_OPTS),
  ]);
}

export async function loadRole(): Promise<string | null> {
  return getItem(ROLE_KEY, STORE_OPTS);
}

export async function saveRole(role: string): Promise<void> {
  await setItem(ROLE_KEY, role, STORE_OPTS);
}

export async function clearRole(): Promise<void> {
  await deleteItem(ROLE_KEY, STORE_OPTS);
}
