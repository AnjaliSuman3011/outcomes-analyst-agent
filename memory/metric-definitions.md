# Metric definitions (v1) — status per metric

Data access: Metabase session login, MySQL read replica, DB id 69 (`tools/metabase_query.py`).
LSQ (leads) lives in a **different Metabase DB, id 434** — use `--db 434` (access confirmed).
LSQ Career Services (referral data) is **DB 437** — use `--db 437` (access confirmed Nov 6 2026).

## 1. Active JDs (monthly) — LOCKED (v1)
Canonical source: stable card **7836** "All active JD's_2026" (production, Metabase DB 69).
- **Use the stable definition, never the live one** (7295 / 7845). The live version adds
  `stage NOT REGEXP 'closed'` on the *current* stage, so past months re-compute as JDs close.
- **Active date** = earliest audit timestamp (`MIN(revinfo.revtstmp)` via `user_hiring_round_aud`
  -> `revinfo`) of any `user_hiring_round` where `scheduled_at IS NOT NULL` AND
  `round_type != 'RESUME_SCREENING'`. Joins: `user_hiring_round` -> `hiring_request`
  (for `posted_at`), `user_hiring_round_aud`, `revinfo`.
- **Monthly count** = JDs whose active date falls in that month.
- **Permanent cutoff:** `hiring_request.posted_at >= '2025-10-01'` (as in 7836). This is part of the
  definition, not a tunable parameter. Do not swap in the older 2024-10-01 cutoff (card 7325).
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
- **Oct 2025 = 63 is a boundary artifact of the cutoff, NOT a trend point** (it reads 90 under the older
  2024-10-01 cutoff). JDs posted before 2025-10-01 are excluded by definition, so Oct 2025 is understated.
  Never present it as a dip. First comparable month is Nov 2025. Oct 2026 is the same under either cutoff.
- **Oct 2026 value history (grows while the month is open):** 64 (Oct 28 AM), 65 (Oct 28), 72 (Nov 4).
  The "64" above was an as-of-Oct-28 figure; the completed month reads 72. State the as-of date.

### Active-JD series, locked definition (queried Nov 4 2026)
Oct-25 63* | Nov 117 | Dec 115 | Jan-26 136 | Feb 108 | Mar 115 | Apr 106 | May 103 | Jun 97 | Jul 98 |
Aug 53 | Sep 65 | Oct 72.  (*boundary artifact)

### Pipeline-break check for the Aug 2026 drop (Nov 4 2026) -- NO BREAK FOUND (INFERRED, not confirmed)
Access limit: DB-read only via Metabase (no cron/job logs, scheduler status, or sheet timestamps), so this is
a data-signature test. The active date is not set by a cron; it is derived at query time from
`revinfo`/`user_hiring_round_aud` rows the app writes on each save. Tests run:
- Audit writes alive: `revinfo` revisions 61k-76k/week every week Jun-Aug 2026 (no gap or hard stop); round and JD
  audit rows present every week. Whole-platform audit volume drifted down (~70k/wk Jun-Jul to ~44-52k/wk Sep).
- No JD with a scheduled non-RS round is missing its audit timestamp (sched-but-no-audit = 0 in every month).
- Audit-based active month matches a scheduled_at-based first-activity month within +/-6 JDs every month
  (Aug: 53 vs 54), so the audit flag does not diverge from the underlying schedule data.
- Newly-active JDs appear on every weekday Jul 13-Aug 24; no gap. No bulk backfill: no two JDs share an
  active-date minute anywhere Jun-Oct 2026.
- The drop shows upstream too: JDs received 230 -> 145 (-37%), JDs with new qualifying rounds ~44/wk -> ~26/wk.
- Activation (active / received) has no cliff: Jul 0.43, Aug 0.37, Sep 0.35, Oct 0.40 (range 0.33-0.50).

## 1b. JD Received (monthly) -- PROVISIONAL PROXY, NOT LOCKED
Proxy = `hiring_request` rows created in the month (IST), excluding the test-company list. (posted_at gives the
same counts for Oct 2025-Oct 2026.) Not reconciled to any team figure. Series (Nov 4 2026):
Oct-25 190 | Nov 257 | Dec 309 | Jan-26 308 | Feb 235 | Mar 262 | Apr 211 | May 240 | Jun 235 | Jul 230 |
Aug 145 | Sep 185 | Oct 182.

## 2. Offers (monthly) — LOCKED (v1, CRIO-ONLY)
**Offers (v1) = Crio offers only.** Source: `user_outcome` on DB 69 (card 7832 logic).
- **Count** = `user_outcome` rows whose `CONVERT_TZ(timestamp,'+00:00','+05:30')` falls in the month.
  Join `hiring_request` on `hiring_request_id` for company/owner. Apply 7832's exclusions:
  `user_id NOT REGEXP 'neill-criodo'` and `hiring_request.company_name NOT REGEXP 'crio'`
  (test accounts). Oct 2026: 9 rows with or without the filters; all `job_application_source = CRIO_REFERRAL`,
  all with a `hiring_request_id`.
- **Oct 2026 = 9** (Crio).
- **MANDATORY WORDING:** the agent must ALWAYS state that this is **Crio offers only** and that
  **Self offers are not in any queryable source** -- they are tracked in the team's manual CS sheet and
  must be added manually. NEVER present the Crio number as "total offers".
- **Known context:** the team sheet shows Oct 2026 total = 20 (9 Crio + 11 Self). The 11 Self are
  manual-only and out of scope for v1. The 9 Crio matches the database exactly.
- **Upgrade path:** if a Self-offers source is ever found, Offers can become Crio + Self (kept as a
  visible split) without changing any other metric.

### Due-diligence trail (do not re-investigate from scratch)
- `user_outcome` Oct 2026: 9 rows, all `CRIO_REFERRAL`, none with NULL `hiring_request_id`, so the
  crio-regex filter in 7832 is NOT dropping Self offers. Only 4 `SELF` rows exist in the whole table,
  all from Jul 2024 (all-time sources: CRIO_REFERRAL 620, CRIO_ASSISTED_APPLY 10, SELF 4, GEEKTRUST 1).
- `user_hiring_request.status = 'OFFERED'` (9 rows updated in Oct 2026) = the SAME 9 user+JD pairs
  and dates as `user_outcome` -- duplicate Crio data, not Self (checked both directions).
- LSQ (DB 434): `Leads.mx_Last_Offer_Date` / `mx_Total_Offers` / `mx_Placed_Account` -- no rows with an
  offer date since Jul 2026. Self opportunities (`mx_Custom_45 = 'Self'`) in Oct are all at stage
  'JD Received' with no offered-profile counts (`mx_Custom_28`).
- DB 69 has no table named like self/offer/placement besides `user_outcome` (and `activity_schedule_for_offering`, 5 rows, unrelated).
- NOT investigated (deliberately deferred): other LSQ ActivityEvents seen in Oct (97, 202, 200, 21, 103,
  203, 22). Only worth a look if someone can say which one means "offer".

## 3. Interview rounds (monthly) — LOCKED (v1)
Source: `user_hiring_round` (DB 69), card 7831 "interview_dump_v3_2026" logic.
- **Grain:** one row per `user_hiring_round` (round-rows, NOT distinct students).
- **Base filters (from 7831):** `user_hiring_round.user_id NOT REGEXP '-crio'`;
  `CONVERT_TZ(hiring_request.posted_at,'+00:00','+05:30') > '2025-07-30'`;
  `hiring_request.company_name <> 'Dummy Company (CS Onboarding)'` (join `hiring_request` on `hiring_request_id`).
- **Month** = `CONVERT_TZ(scheduled_at,'+00:00','+05:30')` falls in the month (IST). This includes
  rounds scheduled LATER in the month that already exist, so the count grows as rounds are created.
- **Round number shift:** `rn = number - 1` if the user+JD (`PARTITION BY user_id, hiring_request.id`,
  window computed on the base-filtered rows, before the month filter) has a `RESUME_SCREENING` round
  numbered 1; else `rn = number`. Rows with `rn <= 0` (the resume-screening round) are not counted.
- **R1 Completed** = `rn = 1` AND `status = 'COMPLETED'` (result CLEARED or NOT_CLEARED; all completed rows
  have one of the two). Total R1 (any status) is a different, larger number -- do not report it as Completed.
- **Total R2** = `rn = 2`, ALL statuses (no completed filter).
- **Total R3+** = `rn >= 3`, ALL statuses ("and above", not exactly 3).
- **As-of date AND time are mandatory.** These counts move after the fact: rounds are created ahead of
  time and CS marks rounds COMPLETED days later (status lag). Every answer must say "as of <date/time>".
- **Validation (sheet pulled Oct 27, ~17:30 IST):** R1 Completed 134, Total R2 47, Total R3+ 10 (sheet also
  quoted total R1 = 475). Reproduced exactly by counting the full October month as it stood at ~17:30 IST on
  Oct 27: rows by `created_at` <= cutoff (R1 total 475, R2 47, R3+ 10) and COMPLETED rows by `updated_at`
  <= cutoff (134). The cutoff is a fitted estimate (updated_at is last-modified, so 133-134 for
  17:00-17:30).
- **Live values for Oct 2026 as of Oct 28 (queried live):** Total R1 518, R1 Completed ~155
  (105 NOT_CLEARED + 49 CLEARED + 1 more updated since; data moves), R2 51, R3+ 11 (10 distinct user+JD).
  The jump vs the sheet is timing, not a definition difference.
- R1 completed by round_type (Oct, thru 27): TECHNICAL 53, TAKE_HOME 49, HR_SCREENING 42, ASSESSMENT 6,
  HR_CALL 5. R1 non-completed statuses: SCHEDULED, NOT_SUBMITTED, NO_SHOW, CANCELLED, RESCHEDULED.

## 4. Leads Generated by channel (monthly) — LOCKED (v1)
Source: LSQ, Metabase **DB 434**, table `ProspectActivity_ExtensionBase` (card 7830 logic).
- **Grain:** one opportunity row, `ActivityEvent = 12000`. NOT distinct prospects
  (Oct 2026: 2,563 rows vs 1,918 distinct prospects).
- **Date:** `CONVERT_TZ(createdon,'+00:00','+05:30')` (IST); month = rows created in that month.
- **Channel split:**
  - Manual = `mx_Custom_50` (Lead_gen_POC) = 'Sahil'
  - Bot    = `mx_Custom_50` = 'Scraping_Tool'
  - Self   = `mx_Custom_45` = 'Self'
  (`mx_Custom_45` alone is NOT the split: its 'Leadgen' value mixes Bot and Manual.)
- **Exclude rows that fit none of the three buckets** (follow the sheet), including the blank
  `mx_Custom_45` row. Do NOT count it as Self (card 7830 does; that breaks the reconciliation:
  Self would be 153, not 152). Total = Manual + Bot + Self.
- **Month-to-date, grows through the month: EVERY answer MUST state its as-of date.**
  A Bot/Manual row can land any day, so a figure is only comparable to another at the same as-of date.
- **Validation:** sheet figures for Oct 2026 were as-of Oct 27: Manual 672, Bot 1,613, Self 152
  (total 2,437). Reproduced exactly for 2026-10-01..2026-10-27. Through Oct 28: Bot 1,689,
  Manual 710, Self 159 (total 2,558).
- Junk/Lost rows are not excluded (7 in Oct, immaterial; the sheet appears not to exclude them).
- Card 5754 is an old 2024 DB-69 job_lead card and is NOT part of this metric.

## 5 (history). Pool DB investigation -- SUPERSEDED by the sheet-sourced lock at the end of this file
Rule given by the team: a student is in the Pool once referral-ready ("Date Referrals Started"); status
(Looking/Paused/Placed) does not decide membership; cumulative, never summed across months.
Sheet reference: Aug 611, Sep 658, Oct 675 (+47, +17).
- **DB 437 is accessible** (`--db 437`, database `qiftsolutech_mxradon`, LSQ Career Services; added to the
  tool's allowlist Nov 6 2026, still SELECT-only). Probed live: `SELECT 1` = 1.
- Candidates tested (cumulative, distinct students, <= month-end) -- NONE reconcile:
  | Candidate | Aug | Sep | Oct |
  |---|---|---|---|
  | Sheet (target) | 611 | 658 | 675 |
  | LSQ activity event 230 "Referral Ready", first occurrence per prospect (437) | 1,569 | 1,659 | 1,732 |
  | `Leads.mx_Referral_Age` -> start = today - age, distinct `mx_Crio_user_id` (437) | 2,701 | 2,851 | 3,110 |
  Event 230 adds ~70-90 students/month; the sheet adds 47 then 17. Both candidates are 2.5-5x too large.
- Facts: 437 `Leads.mx_Career_Services_Status` (Placed 1,839, Paused 901, Looking for Job 666, Pre-referral
  Pause 191, Not Looking 69, ...; blank 11,271). ~3,264 students have a `mx_Referral_Age`. DB 437 has no status
  history, so any status-based cut cannot be rebuilt for past months.
- Conclusion: the pool in the sheet is a narrower population than "everyone ever referral-ready". Need the
  exact membership rule/field (or the sheet's student list for one month) to find the missing filter.
  Do NOT approximate Pool from the sheet.

## §5 addendum — DB fallback result (2026-11-06) — confirms Pool is not DB-derivable
Event-230 ("Referral Ready") cohort on DB 437, cumulative as of Oct 31 = 1,732 (Aug 1,569 / Sep 1,659).
Current-status split: Looking for Job 583, Placed 503, Paused 405, Pre-referral Pause 187, Not Looking 27,
Onboarding Done 24, Onboarding Scheduled 8, blank 3, Referral Ready 2, Terminated 2, Welcome Call Ready 2.
No single or layered cut gives 675 (Excl. Placed ≈ 1,229; Looking for Job alone = 583).
DB 437 holds only CURRENT status (no history), so Aug/Sep membership cannot be rebuilt from status.
Month-on-month growth does not match either: sheet +47 / +17 vs Event-230 +90 / +73.
Closest candidate: none that reconciles. Do NOT approximate Pool from the sheet.
NEED: the Oct 675-student roster (or the sheet's formula / source query) to reverse-engineer the filter.

## 5. Total Users in Pool — LOCKED (v1, SHEET-SOURCED, 2026-11-06)
**Definition:** Total Users in Pool = count of distinct students with Status = "Looking for Job" (+ "Offered") in the
Referral Candidates workbook, "Eligible Candidates" roster, captured at month-end.
- **Source:** the sheet (system of record), NOT a live DB query. Monthly series is hand-captured: Aug 611 / Sep 658 / Oct 675.
  No historical reconstruction is possible or allowed.
- **Point-in-time snapshot; never sum across months.**
- **Caveat:** the DB (Career Services, DB 437) reproduces ~583 "Looking for Job" vs the sheet's ~665 (~14% under, no status
  history), so the DB figure must NOT be quoted as Pool. Not auto-refreshing; always state the snapshot date.
- **Provenance note:** the ~665 (+Offered ~669) current-sheet counts were supplied by the user; the agent did not re-read the sheet.
- Toggle: if the team says drop, remove Pool and call v1 a 4-metric release.

## 1c. Active JD channel split — DROPPED (2026-11-06)
`hiring_request` has no source/channel field: its only attribution columns are `hiring_request_owner` (a person name, 20+
values), `recruitment_ops` (constant 'Siddharth'), `career_services_owner` (blank), `account_manager`, `employment_type`
(FULL_TIME / INTERNSHIP*). Nothing distinguishes bot vs manual vs self. Active JDs are **total-only** in v1. Scope closed.

## Validation run, 2026-11-06 ~13:35 IST — INTERNAL CONSISTENCY ONLY, NOT A CERTIFIED GREEN PASS
No team-confirmed reference answers exist for these 20 questions. Locked queries reproduce their earlier validations
(Active JD series matches exactly Oct-25..Oct-26). Results (all as of Nov 6 ~13:35 IST):
- Leads (channel-sum, Manual/Bot/Self): Aug 812/1897/122 | Sep 719/2880/174 | Oct 792/1950/181 (total 2,923). Nov 1-6: 178/500/21 (699).
  CAVEAT: Self overlaps Manual/Bot in some months (May 52, Jun 55, Jul 4, Sep 3; Aug/Oct 0), so channel sums can exceed the
  row total there. Locked rule does not dedupe; Oct is clean.
- Active JDs: Aug 53, Sep 65, Oct 72, Nov-to-date 14. Rounds (R1 total/R1 completed/R2/R3+): Aug 422/302/58/18, Sep 503/337/46/15,
  Oct 570/223/53/14, Nov-to-date 95/31/9/0. Offers (Crio): Aug 13, Sep 20, Oct 10, Nov-to-date 0 (Oct was 9 on Oct 28).
- Not answerable from the 5 locked metrics: per-BD calls / connect% / JDs punched (Q19, Q20) -- no locked source.

## v1 LOCKED — as of 2026-11-06
Metrics and sources:
1. Leads Generated by channel — LSQ DB 434, `ProspectActivity_ExtensionBase` (ActivityEvent 12000)
2. Active JDs (total only) — DB 69, `hiring_request` + `user_hiring_round` + `user_hiring_round_aud` + `revinfo` (card 7836)
3. Interview rounds (R1 Completed / R2 / R3+) — DB 69, `user_hiring_round` (card 7831)
4. Total Users in Pool — **sheet-sourced** (Referral Candidates workbook, Eligible Candidates); not DB-derivable
5. Offers — **Crio only**, DB 69 `user_outcome` (card 7832); Self offers not queryable
Caveats on this lock: Pool is hand-captured from a sheet (current counts user-supplied, not re-read by the agent);
validation is internal-consistency only, pending team-confirmed answers; Leads channel sums can exceed row totals in
months where Self overlaps Manual/Bot (May/Jun 2026); per-BD calls/connect% (Q19-20) are outside v1;
Active JD Oct sheet 61 vs production 72 remains a recorded discrepancy.
