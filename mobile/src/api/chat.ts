/**
 * `/v1/chat/*` — REST list views + WebSocket helper.
 *
 * The WebSocket lives at `/v1/chat/ws?token=<access_jwt>` (NOT per-thread —
 * a single connection multiplexes via `subscribe` frames per `thread_id`).
 * Inbound frames:
 *   `{type: "subscribe", thread_id}`
 *   `{type: "send", thread_id, kind: "text"|"media", body?, media_asset_id?}`
 * Outbound frames:
 *   `{type: "message", message: ChatMessageOut}`
 *   `{type: "error", error_code, detail}`
 */

import { apiClient } from './client';
import { API_BASE_URL } from './config';
import type { components } from '../../types/api';

type ChatThreadListOut = components['schemas']['ChatThreadListOut'];
type ChatThreadOut = components['schemas']['ChatThreadOut'];
type ChatMessageListOut = components['schemas']['ChatMessageListOut'];
type ChatMessageOut = components['schemas']['ChatMessageOut'];
type ChatMessageCreateIn = components['schemas']['ChatMessageCreateIn'];

export async function listThreads(opts?: {
  limit?: number;
  offset?: number;
}): Promise<ChatThreadListOut> {
  const r = await apiClient.get<ChatThreadListOut>('/v1/chat/threads', { params: opts });
  return r.data;
}

export async function getThread(threadId: string): Promise<ChatThreadOut> {
  const r = await apiClient.get<ChatThreadOut>(`/v1/chat/threads/${threadId}`);
  return r.data;
}

export async function listChatMessages(
  threadId: string,
  opts?: { limit?: number; before_id?: string | null },
): Promise<ChatMessageListOut> {
  const r = await apiClient.get<ChatMessageListOut>(
    `/v1/chat/threads/${threadId}/messages`,
    { params: opts },
  );
  return r.data;
}

export async function postChatMessage(
  threadId: string,
  body: ChatMessageCreateIn,
): Promise<ChatMessageOut> {
  const r = await apiClient.post<ChatMessageOut>(
    `/v1/chat/threads/${threadId}/messages`,
    body,
  );
  return r.data;
}

/**
 * Build the chat WS URL.
 *
 * Backend expects the access token via `?token=<jwt>` query param. We
 * convert `http(s)://host` → `ws(s)://host` using the API base URL the
 * REST client is already targeting.
 */
export function buildChatSocketUrl(accessToken: string): string {
  const wsBase = API_BASE_URL.replace(/^http/, 'ws');
  return `${wsBase}/v1/chat/ws?token=${encodeURIComponent(accessToken)}`;
}
