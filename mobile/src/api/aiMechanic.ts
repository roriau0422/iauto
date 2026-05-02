/**
 * `/v1/ai-mechanic/*` — sessions + multimodal input variants.
 *
 * The four input forks are explicit endpoints, not a single multiplexed
 * route, so we expose them as separate functions. See decision 5 in
 * `docs/ARCHITECTURE.md`.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type SessionCreateIn = components['schemas']['SessionCreateIn'];
type SessionOut = components['schemas']['SessionOut'];
type SessionListOut = components['schemas']['SessionListOut'];
type MessageCreateIn = components['schemas']['MessageCreateIn'];
type MessageListOut = components['schemas']['MessageListOut'];
type AssistantReplyOut = components['schemas']['AssistantReplyOut'];
type VoiceMessageCreateIn = components['schemas']['VoiceMessageCreateIn'];
type VoiceReplyOut = components['schemas']['VoiceReplyOut'];
type VisualMessageCreateIn = components['schemas']['VisualMessageCreateIn'];
type EngineSoundMessageCreateIn = components['schemas']['EngineSoundMessageCreateIn'];
type WarningLightMessageCreateIn = components['schemas']['WarningLightMessageCreateIn'];
type WarningLightReplyOut = components['schemas']['WarningLightReplyOut'];
type MultimodalReplyOut = components['schemas']['MultimodalReplyOut'];

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function listSessions(opts?: {
  limit?: number;
  offset?: number;
}): Promise<SessionListOut> {
  const r = await apiClient.get<SessionListOut>('/v1/ai-mechanic/sessions', {
    params: opts,
  });
  return r.data;
}

export async function createSession(body: SessionCreateIn = {}): Promise<SessionOut> {
  const r = await apiClient.post<SessionOut>('/v1/ai-mechanic/sessions', body);
  return r.data;
}

export async function getSession(sessionId: string): Promise<SessionOut> {
  const r = await apiClient.get<SessionOut>(`/v1/ai-mechanic/sessions/${sessionId}`);
  return r.data;
}

export async function listMessages(sessionId: string): Promise<MessageListOut> {
  const r = await apiClient.get<MessageListOut>(
    `/v1/ai-mechanic/sessions/${sessionId}/messages`,
  );
  return r.data;
}

// ---------------------------------------------------------------------------
// Multimodal forks
// ---------------------------------------------------------------------------

export async function postTextMessage(
  sessionId: string,
  body: MessageCreateIn,
): Promise<AssistantReplyOut> {
  const r = await apiClient.post<AssistantReplyOut>(
    `/v1/ai-mechanic/sessions/${sessionId}/messages`,
    body,
  );
  return r.data;
}

export async function postVoiceMessage(
  sessionId: string,
  body: VoiceMessageCreateIn,
): Promise<VoiceReplyOut> {
  const r = await apiClient.post<VoiceReplyOut>(
    `/v1/ai-mechanic/sessions/${sessionId}/voice`,
    body,
  );
  return r.data;
}

export async function postVisualMessage(
  sessionId: string,
  body: VisualMessageCreateIn,
): Promise<MultimodalReplyOut> {
  const r = await apiClient.post<MultimodalReplyOut>(
    `/v1/ai-mechanic/sessions/${sessionId}/visual`,
    body,
  );
  return r.data;
}

export async function postEngineSoundMessage(
  sessionId: string,
  body: EngineSoundMessageCreateIn,
): Promise<MultimodalReplyOut> {
  const r = await apiClient.post<MultimodalReplyOut>(
    `/v1/ai-mechanic/sessions/${sessionId}/engine-sound`,
    body,
  );
  return r.data;
}

export async function postWarningLightMessage(
  sessionId: string,
  body: WarningLightMessageCreateIn,
): Promise<WarningLightReplyOut> {
  const r = await apiClient.post<WarningLightReplyOut>(
    `/v1/ai-mechanic/sessions/${sessionId}/warning-light`,
    body,
  );
  return r.data;
}
