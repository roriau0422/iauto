/**
 * `/v1/notifications/mine` — list notifications dispatched to the
 * current user. Status counters drive the bell icon badge.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type NotificationDispatchListOut =
  components['schemas']['NotificationDispatchListOut'];

export async function listMyNotifications(opts?: {
  limit?: number;
  offset?: number;
}): Promise<NotificationDispatchListOut> {
  const r = await apiClient.get<NotificationDispatchListOut>('/v1/notifications/mine', {
    params: opts,
  });
  return r.data;
}
