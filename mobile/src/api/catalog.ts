/**
 * `/v1/catalog/*` — country / brand / model taxonomy.
 *
 * Used by valuation (the estimate body needs a `vehicle_brand_id`) and
 * by warehouse SKU forms once we add brand/model linkage.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type VehicleCountryListOut = components['schemas']['VehicleCountryListOut'];
type VehicleBrandListOut = components['schemas']['VehicleBrandListOut'];
type VehicleModelListOut = components['schemas']['VehicleModelListOut'];

export async function listCountries(): Promise<VehicleCountryListOut> {
  const r = await apiClient.get<VehicleCountryListOut>('/v1/catalog/countries');
  return r.data;
}

export async function listBrands(opts?: {
  country_id?: string | null;
}): Promise<VehicleBrandListOut> {
  const r = await apiClient.get<VehicleBrandListOut>('/v1/catalog/brands', { params: opts });
  return r.data;
}

export async function listModels(opts?: {
  brand_id?: string | null;
}): Promise<VehicleModelListOut> {
  const r = await apiClient.get<VehicleModelListOut>('/v1/catalog/models', { params: opts });
  return r.data;
}
