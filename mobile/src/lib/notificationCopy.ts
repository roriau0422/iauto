/**
 * Mongolian glosses for `NotificationDispatchOut.kind`.
 *
 * The backend exposes `kind` as an open `string` on the dispatch row
 * rather than a closed enum — the mapping between the producer side
 * (`backend/app/notifications/handlers.py`) and the consumer side is
 * coordinated through this file. Whenever a new dispatch kind is
 * introduced server-side, add the gloss here so the bell strip + the
 * notifications inbox don't render the raw snake_case identifier.
 */

/** All notification kinds the backend currently emits. */
export type NotificationKind =
  | 'quote_sent'
  | 'reservation_started'
  | 'reservation_confirmed'
  | 'reservation_completed'
  | 'sale_completed'
  | 'review_submitted'
  | 'warehouse_low_stock'
  | 'payment_settled';

const COPY: Record<NotificationKind, string> = {
  quote_sent: 'Үнийн санал ирлээ',
  reservation_started: 'Захиалга нээгдлээ',
  reservation_confirmed: 'Захиалга баталгаажлаа',
  reservation_completed: 'Захиалга хүлээн авлаа',
  sale_completed: 'Худалдаа дууслаа',
  review_submitted: 'Шинэ үнэлгээ',
  warehouse_low_stock: 'Агуулахын үлдэгдэл багасч байна',
  payment_settled: 'Төлбөр хийгдсэн',
};

/**
 * Resolve a Mongolian gloss for a notification kind. Falls back to the
 * raw string when the producer outpaces the copy table — that way an
 * outdated client still surfaces *something* readable instead of a
 * blank cell, but the engineer reviewing the bell strip immediately
 * sees that a new kind needs glossing.
 */
export function notificationLabel(kind: string): string {
  if (kind in COPY) return COPY[kind as NotificationKind];
  return kind;
}
