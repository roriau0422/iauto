/**
 * `/v1/vehicles/*` — XYP lookup plan, registration, ownership list,
 * and per-vehicle service-history endpoints.
 *
 * The XYP lookup itself runs on the device — we just fetch the plan,
 * execute the call against smartcar.mn, and POST the raw response back
 * to `/v1/vehicles` for parsing + ownership pivot insertion. See
 * `src/lib/xypLookup.ts` for the runtime side of that contract.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type LookupPlanOut = components['schemas']['LookupPlanOut'];
type LookupReportIn = components['schemas']['LookupReportIn'];
type LookupReportOut = components['schemas']['LookupReportOut'];
type VehicleListOut = components['schemas']['VehicleListOut'];
type VehicleOut = components['schemas']['VehicleOut'];
type VehicleRegisterIn = components['schemas']['VehicleRegisterIn'];
type VehicleRegisterOut = components['schemas']['VehicleRegisterOut'];
type VehicleServiceHistoryOut = components['schemas']['VehicleServiceHistoryOut'];
type VehicleServiceLogCreateIn = components['schemas']['VehicleServiceLogCreateIn'];
type VehicleServiceLogOut = components['schemas']['VehicleServiceLogOut'];
type MyCarListOut = components['schemas']['MyCarListOut'];

export async function getLookupPlan(): Promise<LookupPlanOut> {
  const r = await apiClient.get<LookupPlanOut>('/v1/vehicles/lookup/plan');
  return r.data;
}

export async function reportLookupFailure(body: LookupReportIn): Promise<LookupReportOut> {
  const r = await apiClient.post<LookupReportOut>('/v1/vehicles/lookup/report', body);
  return r.data;
}

export async function registerVehicle(body: VehicleRegisterIn): Promise<VehicleRegisterOut> {
  const r = await apiClient.post<VehicleRegisterOut>('/v1/vehicles', body);
  return r.data;
}

export async function listMyVehicles(): Promise<VehicleListOut> {
  const r = await apiClient.get<VehicleListOut>('/v1/vehicles/me');
  return r.data;
}

export async function getVehicle(vehicleId: string): Promise<VehicleOut> {
  const r = await apiClient.get<VehicleOut>(`/v1/vehicles/${vehicleId}`);
  return r.data;
}

export async function listServiceHistory(vehicleId: string): Promise<VehicleServiceHistoryOut> {
  const r = await apiClient.get<VehicleServiceHistoryOut>(
    `/v1/vehicles/${vehicleId}/service-history`,
  );
  return r.data;
}

export async function addServiceLog(
  vehicleId: string,
  body: VehicleServiceLogCreateIn,
): Promise<VehicleServiceLogOut> {
  const r = await apiClient.post<VehicleServiceLogOut>(
    `/v1/vehicles/${vehicleId}/service-history`,
    body,
  );
  return r.data;
}

export async function listVehicleTax(vehicleId: string): Promise<MyCarListOut> {
  const r = await apiClient.get<MyCarListOut>(`/v1/vehicles/${vehicleId}/tax`);
  return r.data;
}

export async function listVehicleInsurance(vehicleId: string): Promise<MyCarListOut> {
  const r = await apiClient.get<MyCarListOut>(`/v1/vehicles/${vehicleId}/insurance`);
  return r.data;
}

export async function listVehicleFines(vehicleId: string): Promise<MyCarListOut> {
  const r = await apiClient.get<MyCarListOut>(`/v1/vehicles/${vehicleId}/fines`);
  return r.data;
}
