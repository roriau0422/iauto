/**
 * `/v1/businesses/*` — owner-side business CRUD + brand-coverage pivot.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type BusinessOut = components['schemas']['BusinessOut'];
type BusinessCreateIn = components['schemas']['BusinessCreateIn'];
type BusinessUpdateIn = components['schemas']['BusinessUpdateIn'];
type VehicleBrandCoverageListOut =
  components['schemas']['VehicleBrandCoverageListOut'];
type VehicleBrandCoverageReplaceIn =
  components['schemas']['VehicleBrandCoverageReplaceIn'];

export async function createBusiness(body: BusinessCreateIn): Promise<BusinessOut> {
  const r = await apiClient.post<BusinessOut>('/v1/businesses', body);
  return r.data;
}

export async function getMyBusiness(): Promise<BusinessOut> {
  const r = await apiClient.get<BusinessOut>('/v1/businesses/me');
  return r.data;
}

export async function updateMyBusiness(body: BusinessUpdateIn): Promise<BusinessOut> {
  const r = await apiClient.patch<BusinessOut>('/v1/businesses/me', body);
  return r.data;
}

export async function listMyBrandCoverage(): Promise<VehicleBrandCoverageListOut> {
  const r = await apiClient.get<VehicleBrandCoverageListOut>(
    '/v1/businesses/me/vehicle-brands',
  );
  return r.data;
}

export async function replaceMyBrandCoverage(
  body: VehicleBrandCoverageReplaceIn,
): Promise<VehicleBrandCoverageListOut> {
  const r = await apiClient.put<VehicleBrandCoverageListOut>(
    '/v1/businesses/me/vehicle-brands',
    body,
  );
  return r.data;
}
