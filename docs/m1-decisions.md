# M1 decisions (answers to QA open questions), owner: LeadProjectManager
Final for M1. APPROVE_T 0.80 and HIGH_AMOUNT_T 70000.00 confirmed by Vanessa. Section D15+ answers QA round 2. Where they conflict, later items override earlier ones.

1. Submit returns 201. Routing runs synchronously and the outcome is in the body. A replayed duplicate (same Idempotency-Key, same body) returns 200 with the original body.
2. Schema/format errors (bad JSON, malformed codes, missing required fields) return 422. They are NOT persisted, and the error body is sanitized. Business-rule failures ARE persisted and audited:
   - missing required docs: status `pended_docs`
   - non-covered CPT, ineligible patient, or invalid provider: `in_triage` with the rule reason codes. Adverse determinations always need a human. The system never auto-denies.
3. There is no auto-deny threshold. APPROVE_T defaults to 0.80 (CONFIRMED by Vanessa). Rules pass and score >= APPROVE_T means auto-approve. Everything else goes to triage. TRIAGE_T is dropped. The score does NOT affect queue ordering (see D9).
4. Idempotency uses a required `Idempotency-Key` header, stored with a hash of the request body.
   - Same key, same body: 200 replay.
   - Same key, different body: 409.
5. Status enum: `submitted`, `pended_docs`, `in_triage`, `approved`, `denied`, `withdrawn`. Only a human can set `denied`. A same-status transition is a 409. Rejected transition attempts get an audit row (action=`transition_rejected`, IDs only).
6. Accept full ICD-10-CM, including 7th characters and letters (e.g. S72.001A, M1A.0710). Pattern: `^[A-TV-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$`.
7. Amount ceiling: requested amount above HIGH_AMOUNT_T (default 70000.00, CONFIRMED by Vanessa) goes to triage, even with a high score.
8. Unknown fields: `extra=forbid`, giving a 422 with a sanitized body that never echoes input values.
9. Triage priority: the provider supplies clinical urgency (`Stat` > `Urgent` > `Normal`, default Normal). The queue orders by urgency, then oldest submitted_at, then ClaimID.
10. Metrics:
    - Straight-through rate = auto_approved / persisted claims that reached routing (422s excluded).
    - Latency = submitted_at to final decision (auto or human), plus a separate submitted-to-routing figure.
    - Percentiles use nearest-rank.
11. Score precision: round to DECIMAL(5,4) first, then compare and store the rounded value. Reject scores that are out of range, NaN, or bool; those go to triage as a scorer failure.
12. Uploads: PDF, PNG, JPEG, TIFF; 20 MB max. Uploading to a finalized claim (approved/denied/withdrawn) returns 409. Uploading to a `pended_docs` claim re-runs the rules.
13. Scorer timeout is 5 seconds (config). A late result is discarded and logged with IDs only, and the claim stays in triage.
14. M1 deletes the legacy SQL files and replaces them with synthetic seeds: fake names, example.com emails, invalid-range NPIs and Tax IDs, and fictional practice names.

## Round 2 (answers to QA AQ-1 and items 2-17)
D15. A score of exactly 0.8000 (after rounding) AUTO-APPROVES, since the rule is >=. "Boundary case" in the original brief meant "test it", not "fail safe".
D16. Rounding uses ROUND_HALF_UP to 4 decimal places, matching MySQL DECIMAL.
D17. Legal transitions (everything else returns 409 and is audited as transition_rejected):
- submitted: can go to pended_docs, in_triage, approved, or withdrawn.
- pended_docs: can go to in_triage, approved (via re-run), or withdrawn.
- in_triage: can go to approved, denied, pended_docs (a human requests docs), or withdrawn.
- approved, denied, and withdrawn are terminal.
- Only the submitting provider may withdraw, and only before the claim is terminal.
D18. A missing or empty Idempotency-Key returns 400 (error code idempotency_key_required). A 422 is not persisted, so its key is not consumed and can be reused.
D19. The body hash is SHA-256 over canonical JSON (sorted keys, no insignificant whitespace, UTF-8). If a request arrives with the same key while the first is still in flight, it gets 409 (request_in_progress).
D20. Unknown codes and IDs:
- A well-formed but unknown CPT is persisted and goes to in_triage (reason non_covered_code).
- A well-formed but unknown patient_id or provider_id returns 422 (unknown_reference), sanitized, because it can't be persisted.
D21. The ICD-10 regex is ^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$, which allows U codes such as U07.1. The CPT format is ^\d{4}[0-9FT]$, so Category II/III codes are format-valid; coverage decides what happens to them (non-covered goes to triage).
D22. Scorer return types:
- float, int, and Decimal are accepted and converted to Decimal.
- bool, str, None, NaN, and anything out of [0,1] count as a scorer failure and go to in_triage.
D23. Human decision endpoint:
- Path: POST /claims/{id}/decision.
- Body: decision (approved, denied, or pended_docs); reason_code (required for denied and pended_docs); approved_amount (optional, defaults to the requested amount, must be <= requested); notes (optional).
- The reviewer is identified by the X-Reviewer-Id header (M1 auth stub; a missing header returns 401).
- Responses: 200 with the updated claim; 404 if the claim doesn't exist; 409 for an illegal or concurrent transition.
D24. Uploads:
- The 20 MiB limit is 20*1024*1024 bytes. Over the limit returns 413.
- The file type is checked by magic bytes. A mismatch or disallowed type returns 415.
- Uploads are allowed on submitted, pended_docs, and in_triage claims. A terminal claim returns 409.
- Only an upload to a pended_docs claim triggers a re-run.
D25. Queue order follows D9 only: urgency, then oldest submitted_at, then ClaimID. The score is not used.
D26. The straight-through rate denominator is all persisted claims except withdrawn ones. pended_docs claims count in the denominator.
D27. When several rules fail, every failure is recorded. Status precedence: any non-document failure (non-covered, ineligible, invalid provider, amount over the ceiling) sends the claim to in_triage. Only when missing documents is the sole failure does it go to pended_docs.
D28. A re-run after an upload runs the full rules check AND calls the scorer again. Audit actions: document_uploaded, then rules_rerun, then routed. The latency clock keeps the original submitted_at.
D29. requested_amount must be > 0.00 (0 or negative returns 422). The ceiling applies to the claim's total requested amount; M1 has no claim lines.
D30. Required documents in M1 are letter_of_medical_necessity and clinical_notes for every claim. Per-CPT and per-payer requirements come in M2 from research/prior-auth-rules.json.
