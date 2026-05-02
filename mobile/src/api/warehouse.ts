/**
 * `/v1/warehouse/*` — SKU CRUD + stock movements (business-side only).
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type SkuListOut = components['schemas']['SkuListOut'];
type SkuOut = components['schemas']['SkuOut'];
type SkuDetailOut = components['schemas']['SkuDetailOut'];
type SkuCreateIn = components['schemas']['SkuCreateIn'];
type SkuUpdateIn = components['schemas']['SkuUpdateIn'];
type SkuDeleteOut = components['schemas']['SkuDeleteOut'];
type StockMovementListOut = components['schemas']['StockMovementListOut'];
type StockMovementCreateIn = components['schemas']['StockMovementCreateIn'];
type StockMovementCreatedOut = components['schemas']['StockMovementCreatedOut'];

export async function listSkus(opts?: {
  q?: string | null;
  limit?: number;
  offset?: number;
}): Promise<SkuListOut> {
  const r = await apiClient.get<SkuListOut>('/v1/warehouse/skus', { params: opts });
  return r.data;
}

export async function createSku(body: SkuCreateIn): Promise<SkuOut> {
  const r = await apiClient.post<SkuOut>('/v1/warehouse/skus', body);
  return r.data;
}

export async function getSku(skuId: string): Promise<SkuDetailOut> {
  const r = await apiClient.get<SkuDetailOut>(`/v1/warehouse/skus/${skuId}`);
  return r.data;
}

export async function updateSku(skuId: string, body: SkuUpdateIn): Promise<SkuOut> {
  const r = await apiClient.patch<SkuOut>(`/v1/warehouse/skus/${skuId}`, body);
  return r.data;
}

export async function deleteSku(skuId: string): Promise<SkuDeleteOut> {
  const r = await apiClient.delete<SkuDeleteOut>(`/v1/warehouse/skus/${skuId}`);
  return r.data;
}

export async function listMovements(
  skuId: string,
  opts?: { limit?: number; offset?: number },
): Promise<StockMovementListOut> {
  const r = await apiClient.get<StockMovementListOut>(
    `/v1/warehouse/skus/${skuId}/movements`,
    { params: opts },
  );
  return r.data;
}

export async function recordMovement(
  skuId: string,
  body: StockMovementCreateIn,
): Promise<StockMovementCreatedOut> {
  const r = await apiClient.post<StockMovementCreatedOut>(
    `/v1/warehouse/skus/${skuId}/movements`,
    body,
  );
  return r.data;
}
