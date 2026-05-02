/**
 * `/v1/me` — current user.
 *
 * Lightweight idempotent fetch backed by the access token. Cheaper than
 * burning a refresh token, so the auth store hydrates with this once a
 * `/v1/auth/me` analogue exists.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

export type UserOut = components['schemas']['UserOut'];

export async function fetchMe(): Promise<UserOut> {
  const r = await apiClient.get<UserOut>('/v1/me');
  return r.data;
}
