/**
 * Axios client with bearer-token + automatic refresh on 401.
 *
 * Behaviour:
 *   - Attach `Authorization: Bearer <access>` if we have one.
 *   - On a 401 response, attempt one refresh, replay the original
 *     request, and bail out (logout) if the refresh itself fails.
 *   - In-flight refreshes are deduped — only one network refresh at
 *     a time, even if 50 requests fire in parallel right after the
 *     access token expired.
 *
 * The "logout" callback is registered by the auth store at module
 * boot so the client can wipe state without a circular import.
 */

import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';

import { API_BASE_URL } from './config';
import { clearTokens, loadTokens, saveTokens } from './tokens';

let onLogout: (() => void) | null = null;
export function setOnLogout(cb: () => void) {
  onLogout = cb;
}

let inflightRefresh: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (inflightRefresh) return inflightRefresh;
  inflightRefresh = (async () => {
    const tokens = await loadTokens();
    if (!tokens?.refresh) return null;
    try {
      const resp = await axios.post(
        `${API_BASE_URL}/v1/auth/refresh`,
        { refresh_token: tokens.refresh },
        { timeout: 15000 },
      );
      const data = resp.data as { access_token: string; refresh_token: string };
      await saveTokens({ access: data.access_token, refresh: data.refresh_token });
      return data.access_token;
    } catch {
      await clearTokens();
      onLogout?.();
      return null;
    } finally {
      inflightRefresh = null;
    }
  })();
  return inflightRefresh;
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

apiClient.interceptors.request.use(async (cfg: InternalAxiosRequestConfig) => {
  const tokens = await loadTokens();
  if (tokens?.access) {
    cfg.headers.set('Authorization', `Bearer ${tokens.access}`);
  }
  return cfg;
});

apiClient.interceptors.response.use(
  (r) => r,
  async (err: AxiosError) => {
    const original = err.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;
    if (!original || err.response?.status !== 401 || original._retried) {
      throw err;
    }
    // Don't try to refresh on the refresh endpoint itself.
    if (original.url?.includes('/v1/auth/refresh')) {
      throw err;
    }
    original._retried = true;
    const fresh = await refreshAccessToken();
    if (!fresh) throw err;
    original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${fresh}` };
    return apiClient.request(original);
  },
);
