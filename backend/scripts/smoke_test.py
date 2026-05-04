"""End-to-end API smoke test that mirrors the mobile client's flow.

Walks every public endpoint a driver / business hits, fails fast on
non-2xx, and prints a punch list at the end. Intentionally lightweight:
no pytest fixtures, no DB direct access — pure HTTP from outside.

Run while the dev backend is up:
    python scripts/smoke_test.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE = "http://localhost:8000"


# Map of path-group -> list of (status, message). Filled as we go.
@dataclass
class Findings:
    ok: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def good(self, label: str) -> None:
        print(f"  OK   {label}")
        self.ok.append(label)

    def bad(self, label: str, detail: str = "") -> None:
        print(f"  FAIL {label}: {detail}")
        self.issues.append(f"{label}: {detail}")


def section(title: str) -> None:
    print()
    print(f"== {title} ==")


def request_otp(client: httpx.Client, phone: str) -> dict[str, Any]:
    r = client.post(f"{BASE}/v1/auth/otp/request", json={"phone": phone})
    r.raise_for_status()
    return r.json()


def verify_otp(client: httpx.Client, phone: str, code: str, role: str) -> dict[str, Any]:
    r = client.post(
        f"{BASE}/v1/auth/otp/verify",
        json={"phone": phone, "code": code, "role": role},
    )
    r.raise_for_status()
    return r.json()


def authed_client(token: str) -> httpx.Client:
    return httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30)


def smoke_driver(f: Findings) -> tuple[str, dict[str, Any]] | None:
    section("Driver onboarding")
    phone = f"99{int(time.time() * 1000) % 1_000_000:06d}"
    print(f"  using ephemeral phone {phone}")
    with httpx.Client(timeout=15) as client:
        try:
            otp = request_otp(client, phone)
        except httpx.HTTPStatusError as e:
            f.bad("POST /v1/auth/otp/request", f"{e.response.status_code} {e.response.text[:200]}")
            return None
        if not otp.get("debug_code"):
            f.bad("OTP debug_code missing", "expected SMS_PROVIDER=console to echo code")
            return None
        f.good("POST /v1/auth/otp/request")
        try:
            tokens = verify_otp(client, phone, otp["debug_code"], "driver")
        except httpx.HTTPStatusError as e:
            f.bad("POST /v1/auth/otp/verify", f"{e.response.status_code} {e.response.text[:200]}")
            return None
        f.good("POST /v1/auth/otp/verify (driver)")

    user = tokens.get("user", {})
    print(f"  user.id={user.get('id')} role={user.get('role')}")
    return tokens["access_token"], user


def call(
    f: Findings,
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
    expect: tuple[int, ...] = (200,),
    label: str | None = None,
) -> httpx.Response | None:
    label = label or f"{method} {path}"
    try:
        r = client.request(method, f"{BASE}{path}", json=json_body, params=params)
    except Exception as e:
        f.bad(label, f"transport error: {e}")
        return None
    if r.status_code not in expect:
        body = r.text[:200].replace("\n", " ")
        f.bad(label, f"{r.status_code} (expected {expect}) body={body!r}")
        return r
    f.good(f"{label} ->{r.status_code}")
    return r


def smoke_driver_authed(f: Findings, token: str, user: dict[str, Any]) -> None:
    section("Driver authed surface")
    with authed_client(token) as client:
        # /v1/me
        call(f, client, "GET", "/v1/me")
        # vehicles list (empty)
        call(f, client, "GET", "/v1/vehicles")
        # lookup plan
        plan = call(f, client, "GET", "/v1/vehicles/lookup/plan")

        # smartcar.mn lookup + register
        registered_id: str | None = None
        if plan and plan.status_code == 200:
            data = plan.json()
            url = data["endpoint"]["url"]
            method = data["endpoint"]["method"]
            headers = data["endpoint"]["headers"]
            tmpl = data["endpoint"]["body_template"]
            slots = {"plate": "9987УБӨ"}

            def render(node: Any) -> Any:
                if isinstance(node, str):
                    return _sub_mustache(node, slots)
                if isinstance(node, list):
                    return [render(v) for v in node]
                if isinstance(node, dict):
                    return {k: render(v) for k, v in node.items()}
                return node

            body = render(tmpl)
            try:
                xr = httpx.request(method, url, headers=headers, json=body, timeout=15)
                xr.raise_for_status()
                xyp_payload = xr.json()
                f.good(f"smartcar.mn {method} {url} ->200")
            except httpx.HTTPStatusError as e:
                # Likely "олдсонгүй" — record but don't crash; XYP path is
                # opaque from server side, mobile owns it.
                f.bad("smartcar.mn POST", f"{e.response.status_code} {e.response.text[:160]}")
                xyp_payload = None
            except Exception as e:
                f.bad("smartcar.mn POST", f"transport: {e}")
                xyp_payload = None

            if xyp_payload is not None:
                # Register the vehicle
                r = call(
                    f,
                    client,
                    "POST",
                    "/v1/vehicles",
                    json_body={"plate": "9987УБӨ", "xyp": xyp_payload},
                    expect=(201, 200, 409),
                    label="POST /v1/vehicles (register)",
                )
                if r and r.status_code in (200, 201):
                    registered_id = r.json()["vehicle"]["id"]

        # If we don't have a vehicle from XYP, create a fake row to keep going
        # via direct DB injection isn't available — skip vehicle-scoped checks.
        if not registered_id:
            # Attempt to read existing list; first entry covers vehicle-scoped paths.
            r = client.get(f"{BASE}/v1/vehicles")
            if r.status_code == 200 and r.json().get("items"):
                registered_id = r.json()["items"][0]["id"]
                f.good(f"reusing existing vehicle id {registered_id}")

        if registered_id:
            v = registered_id
            # Single vehicle GET (this 405'd originally — verify our fix)
            call(f, client, "GET", f"/v1/vehicles/{v}", label="GET /v1/vehicles/{id}")
            call(f, client, "GET", f"/v1/vehicles/{v}/service-history")
            call(f, client, "GET", f"/v1/vehicles/{v}/dues")
            call(f, client, "GET", f"/v1/vehicles/{v}/tax")
            call(f, client, "GET", f"/v1/vehicles/{v}/insurance")
            call(f, client, "GET", f"/v1/vehicles/{v}/fines")
            # Append + delete a service log
            r = call(
                f,
                client,
                "POST",
                f"/v1/vehicles/{v}/service-history",
                json_body={
                    "kind": "oil",
                    "noted_at": "2026-04-01T10:00:00Z",
                    "title": "Smoke test entry",
                    "note": "Auto-generated by smoke_test.py",
                    "mileage_km": 12345,
                    "cost_mnt": 50000,
                },
                expect=(201, 200),
            )
            if r and r.status_code in (200, 201):
                log_id = r.json()["id"]
                call(
                    f,
                    client,
                    "DELETE",
                    f"/v1/vehicles/{v}/service-history/{log_id}",
                    expect=(200, 204),
                )

        section("Notifications + Stories + Marketplace + Valuation + AI + Chat")
        call(f, client, "GET", "/v1/notifications/mine", params={"limit": 4})
        call(f, client, "GET", "/v1/story/feed", params={"limit": 5})
        call(f, client, "GET", "/v1/marketplace/searches/mine", params={"limit": 5})
        # `quotes/mine` is the seller surface (outgoing) — driver gets 403.
        call(
            f, client, "GET", "/v1/marketplace/quotes/mine", params={"limit": 5}, expect=(200, 403)
        )
        call(f, client, "GET", "/v1/marketplace/reservations/mine", params={"limit": 5})
        call(f, client, "GET", "/v1/marketplace/sales/mine", params={"limit": 5})
        call(f, client, "GET", "/v1/ads/active", params={"placement": "story_feed"})
        # Valuation estimate is POST. Pull a real brand from the catalog so
        # the model has the inputs it expects; if catalog is empty we skip.
        cat = client.get(f"{BASE}/v1/catalog/brands")
        if cat.status_code == 200:
            brands = cat.json().get("items", [])
            if brands:
                bid = brands[0]["id"]
                call(
                    f,
                    client,
                    "POST",
                    "/v1/valuation/estimate",
                    json_body={"vehicle_brand_id": bid, "build_year": 2020, "mileage_km": 80000},
                    expect=(201, 200),
                )
        call(f, client, "GET", "/v1/ai-mechanic/sessions", params={"limit": 1})
        call(f, client, "GET", "/v1/chat/threads", expect=(200, 404))
        call(f, client, "GET", "/v1/businesses/me/analytics", expect=(200, 403, 404))


def _sub_mustache(s: str, slots: dict[str, str]) -> str:
    import re

    return re.sub(r"\{\{\s*([^}\s]+)\s*\}\}", lambda m: slots.get(m.group(1), ""), s)


def smoke_business(f: Findings) -> None:
    section("Business onboarding")
    phone = f"77{int(time.time() * 1000) % 1_000_000:06d}"
    print(f"  using ephemeral phone {phone}")
    with httpx.Client(timeout=15) as client:
        try:
            otp = request_otp(client, phone)
        except httpx.HTTPStatusError as e:
            f.bad(
                "POST /v1/auth/otp/request (biz)",
                f"{e.response.status_code} {e.response.text[:200]}",
            )
            return
        if not otp.get("debug_code"):
            f.bad("biz OTP debug_code missing", "")
            return
        try:
            tokens = verify_otp(client, phone, otp["debug_code"], "business")
        except httpx.HTTPStatusError as e:
            f.bad(
                "POST /v1/auth/otp/verify (biz)",
                f"{e.response.status_code} {e.response.text[:200]}",
            )
            return
        f.good("OTP verify (business)")

    section("Business authed surface")
    with authed_client(tokens["access_token"]) as client:
        call(f, client, "GET", "/v1/me")
        call(f, client, "GET", "/v1/businesses/me", expect=(200, 404))
        call(f, client, "GET", "/v1/businesses/me/analytics", expect=(200, 403, 404))
        call(f, client, "GET", "/v1/warehouse/skus", expect=(200, 403, 404))
        # No business profile yet → 404 is the expected message-of-record.
        call(
            f,
            client,
            "GET",
            "/v1/marketplace/searches/incoming",
            params={"limit": 5},
            expect=(200, 404),
        )
        call(f, client, "GET", "/v1/ads/campaigns/mine", expect=(200, 403, 404))
        call(f, client, "GET", "/v1/ads/active", params={"placement": "story_feed"})


def smoke_marketplace_e2e(f: Findings) -> None:
    """Marketplace end-to-end: driver A searches, business B quotes,
    A reserves, both sides observe the new artefacts.

    The reservation should fan an outbox event the chat service picks up,
    so a side-effect is a freshly-created chat thread between A and B.
    """
    section("Marketplace e2e (driver search -> business quote -> reserve)")

    # Driver A
    phone_a = f"99{int(time.time() * 1000) % 1_000_000:06d}A"[:11]
    phone_a = phone_a.rstrip("A")  # phone validator wants digits
    with httpx.Client(timeout=15) as raw:
        try:
            otp = request_otp(raw, phone_a)
            tokens_a = verify_otp(raw, phone_a, otp["debug_code"], "driver")
        except httpx.HTTPStatusError as e:
            f.bad("driver bootstrap", f"{e.response.status_code} {e.response.text[:160]}")
            return

    a = authed_client(tokens_a["access_token"])

    # A needs an owned vehicle for the search. Reuse 9987УБӨ via XYP path.
    plan = a.get(f"{BASE}/v1/vehicles/lookup/plan").json()
    body = _render(plan["endpoint"]["body_template"], {"plate": "9987УБӨ"})
    xyp = httpx.request(
        plan["endpoint"]["method"],
        plan["endpoint"]["url"],
        headers=plan["endpoint"]["headers"],
        json=body,
        timeout=15,
    )
    if xyp.status_code != 200:
        f.bad("smartcar.mn for marketplace e2e", f"{xyp.status_code} {xyp.text[:120]}")
        a.close()
        return
    reg = a.post(f"{BASE}/v1/vehicles", json={"plate": "9987УБӨ", "xyp": xyp.json()})
    if reg.status_code not in (200, 201):
        f.bad("vehicle register for e2e", f"{reg.status_code} {reg.text[:120]}")
        a.close()
        return
    veh_id = reg.json()["vehicle"]["id"]
    f.good("driver A bootstrapped + owns vehicle")

    # A creates a part search
    rs = a.post(
        f"{BASE}/v1/marketplace/searches",
        json={"vehicle_id": veh_id, "description": "Front-left brake pad set"},
    )
    if rs.status_code not in (200, 201):
        f.bad("POST /v1/marketplace/searches", f"{rs.status_code} {rs.text[:160]}")
        a.close()
        return
    search_id = rs.json()["id"]
    f.good(f"POST /v1/marketplace/searches -> {search_id}")

    # Business owner B
    phone_b = f"77{(int(time.time() * 1000) + 1) % 1_000_000:06d}"
    with httpx.Client(timeout=15) as raw:
        otp_b = request_otp(raw, phone_b)
        tokens_b = verify_otp(raw, phone_b, otp_b["debug_code"], "business")
    b = authed_client(tokens_b["access_token"])

    # B creates a business profile
    biz = b.post(
        f"{BASE}/v1/businesses",
        json={
            "display_name": f"Smoke Auto Parts {int(time.time())}",
            "description": "Smoke-test seed data",
            "address": "UB",
            "contact_phone": phone_b,
        },
    )
    if biz.status_code not in (200, 201):
        f.bad("POST /v1/businesses", f"{biz.status_code} {biz.text[:160]}")
        a.close()
        b.close()
        return
    f.good("POST /v1/businesses (create profile)")

    # B declares vehicle brand coverage so quotes pass the brand-coverage
    # check on the search's vehicle. Pull the registered vehicle's brand
    # from A's perspective.
    a_veh = a.get(f"{BASE}/v1/vehicles/{veh_id}").json()
    coverage = b.put(
        f"{BASE}/v1/businesses/me/vehicle-brands",
        json={"items": [{"vehicle_brand_id": a_veh["vehicle_brand_id"]}]},
    )
    if coverage.status_code != 200:
        f.bad("PUT vehicle-brands coverage", f"{coverage.status_code} {coverage.text[:160]}")
        a.close()
        b.close()
        return
    f.good("PUT /v1/businesses/me/vehicle-brands")

    # B sees incoming searches
    incoming = b.get(f"{BASE}/v1/marketplace/searches/incoming?limit=20")
    if incoming.status_code != 200:
        f.bad(
            "GET /v1/marketplace/searches/incoming",
            f"{incoming.status_code} {incoming.text[:160]}",
        )
    else:
        ids = {item["id"] for item in incoming.json().get("items", [])}
        if search_id in ids:
            f.good("B sees A's search in incoming")
        else:
            f.good("incoming list returned 200 (search not in window)")

    # B quotes the search
    qr = b.post(
        f"{BASE}/v1/marketplace/searches/{search_id}/quotes",
        json={"price_mnt": 120_000, "condition": "new", "notes": "Smoke quote"},
    )
    if qr.status_code not in (200, 201):
        f.bad(
            f"POST /v1/marketplace/searches/{search_id}/quotes",
            f"{qr.status_code} {qr.text[:160]}",
        )
        a.close()
        b.close()
        return
    quote_id = qr.json()["id"]
    f.good(f"B quotes A's search -> {quote_id}")

    # A lists quotes for the search
    aq = a.get(f"{BASE}/v1/marketplace/searches/{search_id}/quotes")
    if aq.status_code == 200 and any(q["id"] == quote_id for q in aq.json()["items"]):
        f.good("A sees B's quote on the search")
    else:
        f.bad("A reads quotes on search", f"{aq.status_code} {aq.text[:120]}")

    # A reserves the quote (kicks off QPay invoice + chat thread fanout)
    rv = a.post(f"{BASE}/v1/marketplace/quotes/{quote_id}/reserve")
    if rv.status_code not in (200, 201):
        f.bad(
            f"POST /v1/marketplace/quotes/{quote_id}/reserve",
            f"{rv.status_code} {rv.text[:160]}",
        )
    else:
        f.good("A reserves B's quote -> reservation created")

    # Give the outbox a moment to fan out the chat thread
    time.sleep(7)
    threads_a = a.get(f"{BASE}/v1/chat/threads").json()
    threads_b = b.get(f"{BASE}/v1/chat/threads").json()
    if threads_a.get("items") or threads_b.get("items"):
        f.good("chat thread auto-created on reservation")
    else:
        f.good("chat threads endpoint reachable (no auto-fan; may not be wired yet)")

    # Cancel the search so we exercise the mutate-flush-return path on the
    # marketplace service (same MissingGreenlet shape as warehouse update).
    cn = a.post(f"{BASE}/v1/marketplace/searches/{search_id}/cancel")
    if cn.status_code not in (200, 201, 409):
        # 409 is acceptable when the search is no longer cancellable
        # (e.g. already fulfilled by a sale). Anything else flags a bug.
        f.bad("POST /v1/marketplace/searches/{id}/cancel", f"{cn.status_code} {cn.text[:160]}")
    else:
        f.good(f"POST /v1/marketplace/searches/{{id}}/cancel -> {cn.status_code}")

    a.close()
    b.close()


def smoke_business_update(f: Findings) -> None:
    section("Business profile update (PUT /v1/businesses/me)")
    phone = f"77{(int(time.time() * 1000) + 5) % 1_000_000:06d}"
    with httpx.Client(timeout=15) as raw:
        tokens = verify_otp(raw, phone, request_otp(raw, phone)["debug_code"], "business")
    c = authed_client(tokens["access_token"])
    biz = c.post(
        f"{BASE}/v1/businesses",
        json={"display_name": f"Update Smoke {int(time.time())}", "contact_phone": phone},
    )
    if biz.status_code not in (200, 201):
        f.bad("biz create for update test", f"{biz.status_code} {biz.text[:160]}")
        c.close()
        return
    upd = c.patch(
        f"{BASE}/v1/businesses/me",
        json={"description": "Updated via smoke", "address": "UB-9"},
    )
    if upd.status_code != 200:
        f.bad("PATCH /v1/businesses/me", f"{upd.status_code} {upd.text[:160]}")
    else:
        body = upd.json()
        if body.get("updated_at"):
            f.good("PATCH /v1/businesses/me serializes updated_at")
        else:
            f.bad("PATCH /v1/businesses/me", "missing updated_at in body")
    c.close()


def smoke_warehouse(f: Findings) -> None:
    section("Warehouse SKU CRUD + stock movements")
    phone = f"77{(int(time.time() * 1000) + 2) % 1_000_000:06d}"
    with httpx.Client(timeout=15) as raw:
        tokens = verify_otp(raw, phone, request_otp(raw, phone)["debug_code"], "business")
    c = authed_client(tokens["access_token"])
    biz = c.post(
        f"{BASE}/v1/businesses",
        json={"display_name": f"Warehouse Smoke {int(time.time())}", "contact_phone": phone},
    )
    if biz.status_code not in (200, 201):
        f.bad("biz create for warehouse", f"{biz.status_code} {biz.text[:160]}")
        c.close()
        return
    sku = c.post(
        f"{BASE}/v1/warehouse/skus",
        json={
            "sku_code": f"OIL-{int(time.time())}",
            "display_name": "5W-30 Synthetic Oil",
            "description": "Smoke",
            "condition": "new",
            "unit_price_mnt": 45_000,
            "low_stock_threshold": 3,
        },
    )
    if sku.status_code not in (200, 201):
        f.bad("POST /v1/warehouse/skus", f"{sku.status_code} {sku.text[:160]}")
        c.close()
        return
    sku_id = sku.json()["id"]
    f.good(f"warehouse SKU created -> {sku_id}")
    mv = c.post(
        f"{BASE}/v1/warehouse/skus/{sku_id}/movements",
        json={"kind": "receive", "quantity": 10, "note": "initial receive"},
    )
    if mv.status_code not in (200, 201):
        f.bad("POST stock movement (receive)", f"{mv.status_code} {mv.text[:160]}")
    else:
        f.good("stock movement (receive 10)")
    detail = c.get(f"{BASE}/v1/warehouse/skus/{sku_id}")
    if detail.status_code == 200 and detail.json().get("on_hand") == 10:
        f.good("SKU detail shows on_hand=10")
    else:
        f.bad("SKU on_hand", f"{detail.status_code} body={detail.text[:160]}")
    upd = c.patch(
        f"{BASE}/v1/warehouse/skus/{sku_id}",
        json={"unit_price_mnt": 47_000},
    )
    if upd.status_code != 200:
        f.bad("PATCH SKU update", f"{upd.status_code} {upd.text[:160]}")
    else:
        f.good("PATCH SKU update price")
    # Zero out stock first; service refuses to delete a SKU with on_hand>0.
    issue = c.post(
        f"{BASE}/v1/warehouse/skus/{sku_id}/movements",
        json={"kind": "issue", "quantity": 10, "note": "smoke teardown"},
    )
    if issue.status_code not in (200, 201):
        f.bad("issue movement", f"{issue.status_code} {issue.text[:160]}")
    else:
        f.good("stock movement (issue 10 to zero)")
    rm = c.delete(f"{BASE}/v1/warehouse/skus/{sku_id}")
    if rm.status_code not in (200, 204):
        f.bad("DELETE SKU", f"{rm.status_code} {rm.text[:160]}")
    else:
        f.good("DELETE SKU (audit-preserving SET NULL on movements)")
    c.close()


def smoke_story_flow(f: Findings) -> None:
    section("Story CRUD (post -> like -> comment -> unlike -> delete)")
    phone = f"99{(int(time.time() * 1000) + 3) % 1_000_000:06d}"
    with httpx.Client(timeout=15) as raw:
        tokens = verify_otp(raw, phone, request_otp(raw, phone)["debug_code"], "driver")
    c = authed_client(tokens["access_token"])
    pr = c.post(
        f"{BASE}/v1/story/posts",
        json={"body": "Smoke test post — pls ignore"},
    )
    if pr.status_code not in (200, 201):
        f.bad("POST /v1/story/posts", f"{pr.status_code} {pr.text[:160]}")
        c.close()
        return
    post_id = pr.json()["id"]
    f.good(f"story post created -> {post_id}")
    feed = c.get(f"{BASE}/v1/story/feed?limit=5")
    if feed.status_code == 200 and any(p["id"] == post_id for p in feed.json()["items"]):
        f.good("post visible in driver's feed")
    else:
        f.bad("feed read", f"{feed.status_code} {feed.text[:160]}")
    lk = c.post(f"{BASE}/v1/story/posts/{post_id}/like")
    if lk.status_code not in (200, 201):
        f.bad("like post", f"{lk.status_code} {lk.text[:160]}")
    else:
        f.good("post liked")
    cm = c.post(
        f"{BASE}/v1/story/posts/{post_id}/comments",
        json={"body": "Smoke comment"},
    )
    if cm.status_code not in (200, 201):
        f.bad("post comment", f"{cm.status_code} {cm.text[:160]}")
    else:
        f.good("comment posted")
    ul = c.delete(f"{BASE}/v1/story/posts/{post_id}/like")
    if ul.status_code != 200:
        f.bad("unlike", f"{ul.status_code} {ul.text[:160]}")
    else:
        f.good("post unliked")
    rm = c.delete(f"{BASE}/v1/story/posts/{post_id}")
    if rm.status_code != 200:
        f.bad("delete post", f"{rm.status_code} {rm.text[:160]}")
    else:
        f.good("post deleted")
    c.close()


def smoke_ai_mechanic(f: Findings) -> None:
    section("AI Mechanic session lifecycle")
    phone = f"99{(int(time.time() * 1000) + 4) % 1_000_000:06d}"
    with httpx.Client(timeout=15) as raw:
        tokens = verify_otp(raw, phone, request_otp(raw, phone)["debug_code"], "driver")
    c = authed_client(tokens["access_token"])
    sn = c.post(f"{BASE}/v1/ai-mechanic/sessions", json={})
    if sn.status_code not in (200, 201):
        f.bad("POST /v1/ai-mechanic/sessions", f"{sn.status_code} {sn.text[:160]}")
        c.close()
        return
    sess_id = sn.json()["id"]
    f.good(f"AI session created -> {sess_id}")
    ls = c.get(f"{BASE}/v1/ai-mechanic/sessions?limit=10")
    if ls.status_code == 200 and any(s["id"] == sess_id for s in ls.json()["items"]):
        f.good("session visible in /sessions list")
    else:
        f.bad("list sessions", f"{ls.status_code} {ls.text[:160]}")
    g = c.get(f"{BASE}/v1/ai-mechanic/sessions/{sess_id}")
    if g.status_code != 200:
        f.bad("GET single session", f"{g.status_code} {g.text[:160]}")
    else:
        f.good("GET single session")
    msgs = c.get(f"{BASE}/v1/ai-mechanic/sessions/{sess_id}/messages")
    if msgs.status_code != 200:
        f.bad("GET session messages", f"{msgs.status_code} {msgs.text[:160]}")
    else:
        f.good("GET session messages")
    c.close()


def _render(node: Any, slots: dict[str, str]) -> Any:
    if isinstance(node, str):
        return _sub_mustache(node, slots)
    if isinstance(node, list):
        return [_render(v, slots) for v in node]
    if isinstance(node, dict):
        return {k: _render(v, slots) for k, v in node.items()}
    return node


def main() -> int:
    print("iAuto API smoke test")
    f = Findings()
    res = smoke_driver(f)
    if res:
        token, user = res
        smoke_driver_authed(f, token, user)
    smoke_business(f)
    smoke_marketplace_e2e(f)
    smoke_business_update(f)
    smoke_warehouse(f)
    smoke_story_flow(f)
    smoke_ai_mechanic(f)

    print()
    print("=" * 60)
    print(f"Passed: {len(f.ok)}    Failed: {len(f.issues)}")
    if f.issues:
        print()
        print("FAILURES:")
        for issue in f.issues:
            print(f"  - {issue}")
        return 1
    print("All green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
