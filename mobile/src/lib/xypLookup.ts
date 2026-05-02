/**
 * Client-side XYP lookup runtime.
 *
 * Decision 12 in `docs/ARCHITECTURE.md` — the backend never opens an
 * httpx client to smartcar.mn. Mobile fetches a versioned plan from
 * `/v1/vehicles/lookup/plan`, executes the call against smartcar.mn,
 * and:
 *   - On 200 → POSTs the raw response back to `/v1/vehicles` for parsing
 *     and ownership pivot insertion.
 *   - On `400 + body containing "олдсонгүй"` → user typo. Show the
 *     friendly empty state. Do NOT report.
 *   - On any other non-2xx → POST to `/v1/vehicles/lookup/report` so the
 *     backend pages the operator via Redis-coalesced SMS.
 */

import { getLookupPlan, registerVehicle, reportLookupFailure } from '../api/vehicles';
import type { components } from '../../types/api';

type VehicleRegisterOut = components['schemas']['VehicleRegisterOut'];
type LookupPlanOut = components['schemas']['LookupPlanOut'];

export type XypLookupOutcome =
  | { kind: 'registered'; result: VehicleRegisterOut }
  | { kind: 'not_found'; statusCode: number }
  | { kind: 'gateway_error'; statusCode: number; reportFired: boolean };

const NOT_FOUND_TOKEN = 'олдсонгүй';

/**
 * Render the plan template into a concrete URL/body using `slots`.
 *
 * The plan exposes `body_template` with placeholders like `"{plate}"`
 * and a `slots` map describing which slot each placeholder maps to. We
 * keep the substitution dumb on purpose — string-replace each `{slot}`
 * token in the template with the caller-supplied value.
 */
function renderTemplate(
  template: { [key: string]: unknown },
  slots: { [key: string]: string },
): { [key: string]: unknown } {
  const out: { [key: string]: unknown } = {};
  for (const [k, v] of Object.entries(template)) {
    out[k] = typeof v === 'string' ? substitute(v, slots) : v;
  }
  return out;
}

function substitute(s: string, slots: { [key: string]: string }): string {
  return s.replace(/\{([^}]+)\}/g, (_, key: string) => slots[key] ?? '');
}

export async function runXypLookup(plate: string): Promise<XypLookupOutcome> {
  const plan: LookupPlanOut = await getLookupPlan();
  const slots = { plate };
  const url = substitute(plan.endpoint.url, slots);
  const headers: Record<string, string> = { ...plan.endpoint.headers };
  const body = renderTemplate(plan.endpoint.body_template, slots);

  const init: RequestInit = {
    method: plan.endpoint.method,
    headers,
  };
  if (plan.endpoint.method.toUpperCase() !== 'GET') {
    init.body = JSON.stringify(body);
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    // No HTTP status — report as gateway error 0 so backend can page.
    const errMsg = e instanceof Error ? e.message : String(e);
    const reportRes = await reportLookupFailure({
      plate,
      status_code: 0,
      plan_version: plan.plan_version,
      error_snippet: errMsg.slice(0, 160),
    }).catch(() => null);
    return {
      kind: 'gateway_error',
      statusCode: 0,
      reportFired: reportRes?.alert_fired ?? false,
    };
  }

  if (res.ok) {
    const payload = (await res.json()) as { [key: string]: unknown };
    const result = await registerVehicle({ plate, xyp: payload });
    return { kind: 'registered', result };
  }

  // Read text body for the not-found heuristic.
  let text = '';
  try {
    text = await res.text();
  } catch {
    text = '';
  }

  if (res.status === 400 && text.includes(NOT_FOUND_TOKEN)) {
    return { kind: 'not_found', statusCode: res.status };
  }

  const reportRes = await reportLookupFailure({
    plate,
    status_code: res.status,
    plan_version: plan.plan_version,
    error_snippet: text.slice(0, 160),
  }).catch(() => null);

  return {
    kind: 'gateway_error',
    statusCode: res.status,
    reportFired: reportRes?.alert_fired ?? false,
  };
}
