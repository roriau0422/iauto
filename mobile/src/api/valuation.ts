/**
 * `/v1/valuation/*` — CatBoost-backed estimate + active model status.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type ValuationEstimateIn = components['schemas']['ValuationEstimateIn'];
type ValuationEstimateOut = components['schemas']['ValuationEstimateOut'];
type ValuationModelOut = components['schemas']['ValuationModelOut'];

export async function estimate(body: ValuationEstimateIn): Promise<ValuationEstimateOut> {
  const r = await apiClient.post<ValuationEstimateOut>('/v1/valuation/estimate', body);
  return r.data;
}

export async function getActiveModel(): Promise<ValuationModelOut> {
  const r = await apiClient.get<ValuationModelOut>('/v1/valuation/models/active');
  return r.data;
}
