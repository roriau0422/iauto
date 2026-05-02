/**
 * `/v1/marketplace/*` — driver-side part-search + quote/reserve/sale flow,
 * business-side incoming feed, reviews.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type PartSearchCreateIn = components['schemas']['PartSearchCreateIn'];
type PartSearchOut = components['schemas']['PartSearchOut'];
type PartSearchListOut = components['schemas']['PartSearchListOut'];
type PartSearchCancelOut = components['schemas']['PartSearchCancelOut'];
type QuoteListOut = components['schemas']['QuoteListOut'];
type QuoteOut = components['schemas']['QuoteOut'];
type QuoteCreateIn = components['schemas']['QuoteCreateIn'];
type ReservationOut = components['schemas']['ReservationOut'];
type ReservationListOut = components['schemas']['ReservationListOut'];
type SaleOut = components['schemas']['SaleOut'];
type SaleListOut = components['schemas']['SaleListOut'];
type ReviewCreateIn = components['schemas']['ReviewCreateIn'];
type ReviewOut = components['schemas']['ReviewOut'];
type ReviewListOut = components['schemas']['ReviewListOut'];
type PartSearchStatus = components['schemas']['PartSearchStatus'];

// ---------------------------------------------------------------------------
// Driver — part_search lifecycle
// ---------------------------------------------------------------------------

export async function createPartSearch(body: PartSearchCreateIn): Promise<PartSearchOut> {
  const r = await apiClient.post<PartSearchOut>('/v1/marketplace/searches', body);
  return r.data;
}

export async function listMyPartSearches(opts?: {
  status?: PartSearchStatus | 'all';
  limit?: number;
  offset?: number;
}): Promise<PartSearchListOut> {
  const r = await apiClient.get<PartSearchListOut>('/v1/marketplace/searches/mine', {
    params: opts,
  });
  return r.data;
}

export async function getPartSearch(searchId: string): Promise<PartSearchOut> {
  const r = await apiClient.get<PartSearchOut>(`/v1/marketplace/searches/${searchId}`);
  return r.data;
}

export async function cancelPartSearch(searchId: string): Promise<PartSearchCancelOut> {
  const r = await apiClient.post<PartSearchCancelOut>(
    `/v1/marketplace/searches/${searchId}/cancel`,
  );
  return r.data;
}

export async function listSearchQuotes(
  searchId: string,
  opts?: { limit?: number; offset?: number },
): Promise<QuoteListOut> {
  const r = await apiClient.get<QuoteListOut>(
    `/v1/marketplace/searches/${searchId}/quotes`,
    { params: opts },
  );
  return r.data;
}

// ---------------------------------------------------------------------------
// Business — incoming feed + quote submission
// ---------------------------------------------------------------------------

export async function listIncomingPartSearches(opts?: {
  limit?: number;
  offset?: number;
}): Promise<PartSearchListOut> {
  const r = await apiClient.get<PartSearchListOut>('/v1/marketplace/searches/incoming', {
    params: opts,
  });
  return r.data;
}

export async function submitQuote(searchId: string, body: QuoteCreateIn): Promise<QuoteOut> {
  const r = await apiClient.post<QuoteOut>(
    `/v1/marketplace/searches/${searchId}/quotes`,
    body,
  );
  return r.data;
}

export async function listMyQuotes(opts?: {
  limit?: number;
  offset?: number;
}): Promise<QuoteListOut> {
  const r = await apiClient.get<QuoteListOut>('/v1/marketplace/quotes/mine', {
    params: opts,
  });
  return r.data;
}

// ---------------------------------------------------------------------------
// Reservations
// ---------------------------------------------------------------------------

export async function reserveQuote(quoteId: string): Promise<ReservationOut> {
  const r = await apiClient.post<ReservationOut>(
    `/v1/marketplace/quotes/${quoteId}/reserve`,
  );
  return r.data;
}

export async function listMyReservations(opts?: {
  limit?: number;
  offset?: number;
}): Promise<ReservationListOut> {
  const r = await apiClient.get<ReservationListOut>('/v1/marketplace/reservations/mine', {
    params: opts,
  });
  return r.data;
}

export async function listIncomingReservations(opts?: {
  limit?: number;
  offset?: number;
}): Promise<ReservationListOut> {
  const r = await apiClient.get<ReservationListOut>(
    '/v1/marketplace/reservations/incoming',
    { params: opts },
  );
  return r.data;
}

export async function cancelReservation(reservationId: string): Promise<ReservationOut> {
  const r = await apiClient.post<ReservationOut>(
    `/v1/marketplace/reservations/${reservationId}/cancel`,
  );
  return r.data;
}

export async function completeReservation(reservationId: string): Promise<SaleOut> {
  const r = await apiClient.post<SaleOut>(
    `/v1/marketplace/reservations/${reservationId}/complete`,
  );
  return r.data;
}

// ---------------------------------------------------------------------------
// Sales + reviews
// ---------------------------------------------------------------------------

export async function listMySales(opts?: {
  limit?: number;
  offset?: number;
}): Promise<SaleListOut> {
  const r = await apiClient.get<SaleListOut>('/v1/marketplace/sales/mine', { params: opts });
  return r.data;
}

export async function listOutgoingSales(opts?: {
  limit?: number;
  offset?: number;
}): Promise<SaleListOut> {
  const r = await apiClient.get<SaleListOut>('/v1/marketplace/sales/outgoing', {
    params: opts,
  });
  return r.data;
}

export async function getSale(saleId: string): Promise<SaleOut> {
  const r = await apiClient.get<SaleOut>(`/v1/marketplace/sales/${saleId}`);
  return r.data;
}

export async function listSaleReviews(saleId: string): Promise<ReviewListOut> {
  const r = await apiClient.get<ReviewListOut>(`/v1/marketplace/sales/${saleId}/reviews`);
  return r.data;
}

export async function createReview(
  saleId: string,
  body: ReviewCreateIn,
): Promise<ReviewOut> {
  const r = await apiClient.post<ReviewOut>(`/v1/marketplace/sales/${saleId}/reviews`, body);
  return r.data;
}
