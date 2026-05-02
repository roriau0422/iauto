/**
 * /v1/auth/* endpoint wrappers. Hits the real backend via apiClient.
 */

import { apiClient } from '../api/client';
import type { components } from '../../types/api';

type OtpRequestIn = components['schemas']['OtpRequestIn'];
type OtpRequestOut = components['schemas']['OtpRequestOut'];
type OtpVerifyIn = components['schemas']['OtpVerifyIn'];
type TokenPairOut = components['schemas']['TokenPairOut'];

export async function requestOtp(body: OtpRequestIn): Promise<OtpRequestOut> {
  const r = await apiClient.post<OtpRequestOut>('/v1/auth/otp/request', body);
  return r.data;
}

export async function verifyOtp(body: OtpVerifyIn): Promise<TokenPairOut> {
  const r = await apiClient.post<TokenPairOut>('/v1/auth/otp/verify', body);
  return r.data;
}

export async function logoutSession(refreshToken: string): Promise<void> {
  await apiClient.post('/v1/auth/logout', { refresh_token: refreshToken });
}
