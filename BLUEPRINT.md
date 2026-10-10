# BagKeeper - Blueprint

## 1. Product in one line
Customers tap "call a runner" in a mall; a runner collects, seals and stores their bags; when the
customer is done they tap once more and the runner delivers the bags to their car or location.

## 2. Names (shortlist)
| Name | Why | Check before committing |
|---|---|---|
| **Stowly** (top pick) | Short, friendly, says "stow"; easy .com/app-store handle | domain, trademark |
| **BagKeeper** | Clear, already your folder name; descriptive | likely crowded - harder to trademark |
| **Handsfree / HandsFree Mall** | Sells the benefit | generic, SEO-hard |
| **Tote & Go** | Playful, memorable | "Tote" bags association |
| **Lightly** | "Shop lightly" - emotional benefit | generic |
| **Carryless** | Exactly the promise | slightly negative tone |
| **Holdr** | Modern, short | unusual spelling |
| **BagBuddy** | Friendly, approachable | cutesy for premium malls |

Pick 2-3, check domain + social handles + local trademark registry, then test with 10 shoppers.

## 3. Roles
- **Customer** - requests pickup, tracks bag, requests return, shares handover code.
- **Runner** - claims jobs, photographs + seals bags, stores them, delivers.
- **Admin / mall ops** - sees all orders, disputes, revenue, staff.
- *(Later)* **Mall partner** - read-only dashboard, revenue share.

## 4. Order lifecycle (implemented)
`requested -> assigned -> picked_up (sealed) -> stored -> return_requested -> out_for_delivery -> delivered`
(`cancelled` only before pickup). Every step writes an append-only **event log** (who, what, when).

## 5. Trust and the "nothing is missing" problem (the core of the business)
Layered, cheapest first:
1. **Photo evidence** - contents photographed before sealing, sealed bag photographed after. (done)
2. **Numbered tamper-evident seal** - serial recorded at pickup, customer sees it in-app, runner
   confirms number + intact at delivery; "broken/mismatch" auto-flags to admin. (done)
3. **Handover code** - 4-digit code in the customer's app; delivery cannot complete without it. (done)
4. **Customer present at sealing** - customer taps "I confirm bag sealed" on their own phone (next).
5. **Biometric seal** (your thumb-print idea) - see caveats below.
6. **Smart-lock bags / lockers** - bag locked with a one-time code, or NFC-tag seal scanned by phone.
7. **Insurance cap + declared value** - liability limit in terms; customers declare high-value items,
   which are refused or handled separately. Talk to an insurer early.
8. **Prohibited items list** - no cash, jewellery, electronics-in-bulk, perishables, ID, weapons.
   Legal text agreed at sign-up.

**Thumb-print caveats:** fingerprints are biometric data and regulated in many places (consent,
storage, breach liability). Safer pattern: the fingerprint stays on the *seal device/phone* and only
a "match yes/no" is recorded - never store fingerprint images. A tamper-evident serial-numbered tag
plus photos gets ~90% of the dispute protection at a fraction of the cost and legal risk; add
biometrics later as a premium option with your sealing partner.

## 6. Ideas backlog
**Customer:** live status + ETA, push/SMS/WhatsApp updates, saved car location (drop a pin / photo
of the parking bay), "meet me at exit D", multiple bags per order, tipping, receipts, scheduled
pickups, loyalty points, mall-store partnerships (store staff can call a runner on the customer's behalf).
**Runner:** job queue sorted by distance, in-mall map, barcode/QR scan of bag tags, offline mode,
shift start/stop, earnings screen.
**Ops:** storage slot map, capacity limits, surge pricing on weekends/holidays, dispute workflow with
evidence bundle (photos + timeline), CSV export, staff rota.
**Revenue:** per-hour or per-visit pricing, subscription for frequent shoppers, mall revenue share,
store sponsorship ("bags held free if you spend $X at partner stores"), premium biometric sealing,
gift-wrap / shopping-bag consolidation, holiday packages.
**Growth:** QR codes on mall signage and at store checkouts ("Don't carry it - Stowly it"),
partner with mall management for exclusive storage space, tourist-oriented multi-language UI.
**Risk:** liability and insurance, lost-bag procedure, runner background checks, ID check at
handover for high-value orders, data-protection (phone numbers, photos, location).

## 7. Web first, then mobile
**Yes, build the web version first** - and make it mobile-first (done), because:
- zero install friction: shopper scans a QR at the mall and is in; no app-store approval.
- one codebase serves customers, runners (phone browser) and admins (desktop).
- it validates the business before paying for native apps.

Path to mobile, cheapest first:
1. **PWA (now):** manifest included; add a service worker + icons -> "Add to Home Screen" feels like an app. Web Push works on Android and iOS 16.4+.
2. **Wrapper:** Capacitor around the same web UI to ship to App Store / Play Store (camera, push, GPS).
3. **Native/Flutter** only if you outgrow the above.
The `/api` JSON layer and `services.py` are already UI-agnostic, so a mobile client never needs
backend rewrites - only token auth (JWT) added to `api.py`.

## 8. Architecture
```
Browser/PWA/Mobile  ->  Flask (web.py pages  +  api.py JSON)  ->  services.py (rules)  ->  SQLite
                                                                  uploads/ (photos)
```
Production upgrade path: SQLite -> PostgreSQL; photos -> S3-compatible storage; gunicorn/waitress
behind HTTPS (Caddy/nginx); background jobs (Celery/RQ) for SMS/push; Redis for live updates.

Data model: `users`, `malls`, `orders`, `photos`, `events` (see `bagkeeper/db.py`).

## 9. Roadmap
| Phase | Scope |
|---|---|
| **0 (done)** | Accounts + roles, order flow, photos, seal numbers, handover code, audit log, admin overview, JSON API, PWA manifest |
| **1 Pilot (1 mall)** | SMS/WhatsApp notifications (Twilio), payments (Stripe or local gateway), live auto-refresh, customer seal confirmation, QR bag tags, service worker + icons, HTTPS deploy, terms/liability text |
| **2** | Runner map + ETAs, multi-mall, pricing rules (hourly), ratings, dispute workflow, Postgres |
| **3** | Capacitor mobile apps, push, biometric/NFC seal integration with partner, mall partner portal |

## 10. Open decisions for you
1. Pricing model (flat per visit vs hourly) and currency/payment gateway in your country.
2. Where the bags are physically stored (mall-provided room? lockers?) and who insures them.
3. Seal partner: ask them for (a) unique serials, (b) API/scan method, (c) cost per seal, (d) biometric data handling.
4. Region -> data-protection law (affects photos, phone numbers, any biometrics).
