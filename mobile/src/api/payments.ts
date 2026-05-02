/**
 * `/v1/payments/*` — QPay invoice creation + status polling.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type PaymentIntentCreateIn = components['schemas']['PaymentIntentCreateIn'];
type PaymentIntentCreatedOut = components['schemas']['PaymentIntentCreatedOut'];
type PaymentIntentOut = components['schemas']['PaymentIntentOut'];
type PaymentCheckOut = components['schemas']['PaymentCheckOut'];

export async function createIntent(
  body: PaymentIntentCreateIn,
): Promise<PaymentIntentCreatedOut> {
  const r = await apiClient.post<PaymentIntentCreatedOut>('/v1/payments/intents', body);
  return r.data;
}

export async function getIntent(intentId: string): Promise<PaymentIntentOut> {
  const r = await apiClient.get<PaymentIntentOut>(`/v1/payments/intents/${intentId}`);
  return r.data;
}

export async function checkIntent(intentId: string): Promise<PaymentCheckOut> {
  const r = await apiClient.post<PaymentCheckOut>(`/v1/payments/intents/${intentId}/check`);
  return r.data;
}
