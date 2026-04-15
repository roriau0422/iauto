# QPay — Laravel reference implementation

**Source:** user handover on 2026-04-16, Phase 1 planning session.
**Purpose:** the working Laravel `QpayClient` is the contract session 7 ports
to FastAPI. Match operation names and payload shapes identically — same
discipline as the MessagePro and smartcar.mn ports.

## Operations

1. `getAccessToken() -> str | None`
   - `POST {base_url}/v2/auth/token`
   - Headers: `Authorization: Basic base64(username:password)`
   - Body: empty (per reference — QPay v2 treats Basic auth alone as
     sufficient; no `grant_type` body param)
   - Returns: `response.json()["access_token"]` on HTTP 200, else `None`
     with a warning log
   - **Port note:** token TTL is implicit in the response (`expires_in`
     seconds). The Laravel reference re-fetches per call — we will cache
     the token in Redis under `qpay:token` with a TTL of
     `expires_in - 60` seconds.

2. `checkPayment(token, invoice_id) -> {ok, status, body}`
   - `POST {base_url}/v2/payment/check`
   - Headers: `Authorization: Bearer {token}`, `Accept: application/json`
   - Body: `{"object_type": "INVOICE", "object_id": invoice_id,
     "offset": {"page_number": 1, "page_limit": 100}}`
   - Returns a tuple-ish of the HTTP success flag, status code, and parsed
     body. Used for polling + reconciliation.

3. `createInvoice(token, payload) -> {ok, status, body}`
   - `POST {base_url}/v2/invoice`
   - Headers: `Authorization: Bearer {token}`, `Accept: application/json`
   - Body: the raw payload as assembled by the caller (expects at minimum
     `invoice_code`, `sender_invoice_no`, `invoice_receiver_code`,
     `invoice_description`, `amount`, `callback_url`).
   - Returns the HTTP success flag, status code, and parsed body.

## Credentials (user-provided; TREATED AS COMPROMISED)

```
QPAY_BASE_URL=https://merchant.qpay.mn   # assumed prod; confirm with user
QPAY_USERNAME=NAVIMARKET
QPAY_PASSWORD=uEPU34Xj
QPAY_INVOICE_CODE=NAVIMARKET_INVOICE
QPAY_CALLBACK_URL=                        # to be set once public URL exists
```

**Rotation required** before any production deployment — these were pasted
in chat and must be considered exposed. Same rule as MessagePro credentials
in session 2.

## Laravel source (verbatim)

```php
<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class QpayClient
{
    public function getAccessToken(): ?string
    {
        $baseUrl = rtrim(config('services.qpay.base_url'), '/');
        $username = config('services.qpay.username');
        $password = config('services.qpay.password');

        if (! $username || ! $password) {
            return null;
        }

        $basic = base64_encode($username.':'.$password);
        $response = Http::withHeaders([
            'Authorization' => 'Basic '.$basic,
        ])->post($baseUrl.'/v2/auth/token', []);

        if (! $response->ok()) {
            Log::warning('QPay token failed', [
                'status' => $response->status(),
                'body' => $response->body(),
            ]);

            return null;
        }

        return $response->json('access_token');
    }

    public function checkPayment(string $token, string $invoiceId): array
    {
        $baseUrl = rtrim(config('services.qpay.base_url'), '/');
        $response = Http::withHeaders([
            'Authorization' => 'Bearer '.$token,
            'Accept' => 'application/json',
        ])->post($baseUrl.'/v2/payment/check', [
            'object_type' => 'INVOICE',
            'object_id' => $invoiceId,
            'offset' => ['page_number' => 1, 'page_limit' => 100],
        ]);

        if (! $response->ok()) {
            Log::warning('QPay payment check failed', [
                'status' => $response->status(),
                'body' => $response->body(),
            ]);
        }

        return [
            'ok' => $response->ok(),
            'status' => $response->status(),
            'body' => $response->json(),
        ];
    }

    public function createInvoice(string $token, array $payload): array
    {
        $baseUrl = rtrim(config('services.qpay.base_url'), '/');
        $response = Http::withHeaders([
            'Authorization' => 'Bearer '.$token,
            'Accept' => 'application/json',
        ])->post($baseUrl.'/v2/invoice', $payload);

        if (! $response->ok()) {
            Log::warning('QPay invoice failed', [
                'status' => $response->status(),
                'body' => $response->body(),
            ]);
        }

        return [
            'ok' => $response->ok(),
            'status' => $response->status(),
            'body' => $response->json(),
        ];
    }
}
```

## Open questions for session 7

1. **Webhook signature verification.** QPay v2 invoice payloads include a
   signature on the callback — read the docs at
   `https://developer.qpay.mn/` (fetch via context7/WebFetch before coding)
   to confirm the signing scheme before writing the receiver.
2. **Sandbox vs prod base URL.** User provided credentials that imply prod
   (`NAVIMARKET_INVOICE` code). Confirm whether to test against sandbox
   first (`https://merchant-sandbox.qpay.mn`) or go straight to prod with a
   low-value test invoice.
3. **Invoice code + `sender_invoice_no`.** The `invoice_code` in the env is
   the template; each invoice also needs a unique `sender_invoice_no` —
   our `payment_intent.id` is a natural fit.
