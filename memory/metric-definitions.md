# Metric definitions (v1) — status per metric

Data access: Metabase session login, MySQL read replica, DB id 69 (`tools/metabase_query.py`).
LSQ (leads) lives in a **different Metabase DB, id 434** — use `--db 434` (access confirmed).

## 1. Active JDs (monthly) — LOCKED (v1)
Canonical source: stable card **7836** "All active JD's_2026" (production, Metabase DB 69).
- **Use the stable definition, never the live one** (7295 / 7845). The live version adds
  `stage NOT REGEXP 'closed'` on the *current* stage, so past months re-compute as JDs close.
- **Active date** = earliest audit timestamp (`MIN(revinfo.revtstmp)` via `user_hiring_round_aud`
  -> `revinfo`) of any `user_hiring_round` where `scheduled_at IS NOT NULL` AND
  `round_type != 'RESUME_SCREENING'`. Joins: `user_hiring_round` -> `hiring_request`
  (for `posted_at`), `user_hiring_round_aud`, `revinfo`.
- **Monthly count** = JDs whose active date falls in that month.
- Baseline filter: `hiring_request.posted_at >= '2025-10-01'` (as in 7836).
- **Exclude the test-company list:** "Dummy Company (CS Onboarding)", "test",
  "TIF labs (Fullstack)", "TEST_COMPANY", "test hr creation", "test child"
  (no effect on Oct counts, but always apply).
- **Active JD != JD Received** (they differ ~2x). Never substitute one for the other.
- **Oct 2026 = 64** (canonical).
- **Known discrepancy:** the team spreadsheet shows 61 for Oct 2026. No production query or
  dashboard produces 61; the production definition gives 64, so 64 is canonical and the sheet
  is ~5% off. (Outcomes Dashboard 1231 has no Active JDs figure.)
- **Backfill caveat:** active date is an audit-row timestamp, not `scheduled_at`. Bulk edits or
  backfills of round rows can move a JD into a different month. Mention when relevant.
- Cutoff note: the older card 7325 (`posted_at >= 2024-10-01`) gives Oct 2025 = 90 vs 63 under
  7836; Oct 2026 = 64 either way. Months before Nov 2025 depend on the cutoff.

## 2. Offers — NOT LOCKED
- `user_outcome` (card 7832) Oct 2026 = 9 rows, Oct 2025 = 18; all have `hiring_request_id`
  and all `job_application_source = CRIO_REFERRAL`. So it holds **Crio offers only**; the 9 matches
  "9 Crio". Self offers (expected 11) are NOT in this table — source still to find (likely LSQ).
- 7832 filters: `user_id NOT REGEXP 'neill-criodo'`, `hiring_request.company_name NOT REGEXP 'crio'`;
  placement date = `CONVERT_TZ(timestamp,'+00:00','+05:30')`.

## 3. Interview rounds — SQL fetched (card 7831), NOT LOCKED
- Source `user_hiring_round` + `hiring_request`; excludes `user_id REGEXP '-crio'`, dummy company,
  `posted_at (IST) > 2025-07-30`.
- `revised_round_number` = `number - 1` when the user+JD has a RESUME_SCREENING round numbered 1,
  else `number`. Completion semantics (`result`/`status`) still to confirm.

## 4. Leads by channel — SQL fetched (card 7830, **DB 434 / LSQ**), NOT LOCKED
- Source `ProspectActivity_ExtensionBase` where `ActivityEvent = 12000`, `createdon >= 2025-10-01` (IST).
- Channel signal is `mx_Custom_45` ("Self" / "Leadgen" / other). `opp_source` buckets Self+NULL as
  "Outreach" and everything else as "leadgen". Mapping to Manual / Bot / Self not confirmed.
- Card 7834 (Self JD source, DB 434) = first Self activity per prospect since 2025-07-01.

## 5. Total Users in Pool — no source found in any fetched card
