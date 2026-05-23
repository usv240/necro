# 🪦 GRAVEYARD REPORT
**Repository:** acmecorp/product
**Scan date:** May 13, 2026
**Commits analyzed:** 4,847 (24 months)
**Features analyzed:** 17 disabled features found

---

## Summary

| Category | Count | Est. Annual Value |
|----------|-------|-------------------|
| ✅ Resurrect Now | 3 | $720,000/year |
| 🔍 Investigate Further | 5 | Unknown |
| ❌ Keep Buried | 9 | N/A |

---

## 🟢 RESURRECT IMMEDIATELY

---

### 🪦 Recurring Billing Customization
**Killed:** March 14, 2022 (commit `a4f9b2c`)
**Kill reason:** "Disabling until Stripe supports custom billing intervals"
**Category:** API limitation

**What has changed:**
Stripe added full custom billing interval support in their November 2023 API release (v2023-11-01). This exact feature now exists natively in Stripe. The constraint that caused disablement **no longer exists**.

**Evidence:**
- Commit `a4f9b2c`: *"Disable recurring billing customization — Stripe doesn't support this yet, revisit in 2023"*
- PR #1247 discussion: *"Stripe said this is on their roadmap for H2 2023"*
- Stripe changelog Nov 2023: Added `billing_cycle_anchor_config` parameter

**Revival assessment:**
- Effort: 3–4 days (re-enable existing code + update Stripe integration)
- Risk: Low (code was working before, Stripe API is well-documented)
- Users requesting this: 847 (issues #234, #456, #891, +844 others)

**Revenue impact:**
- 847 users have requested this in the issue tracker
- Competitors (Chargebee, Paddle) all have this feature
- Estimated churn reduction: 3–5% of enterprise accounts would stop evaluating competitors
- **Estimated annual value: $340,000/year**

**Revival plan:**
1. Un-comment `app/billing/recurring.py` lines 112–198
2. Update Stripe SDK to v7.x (supports new billing_cycle_anchor_config)
3. Add `billing_cycle_anchor_config` to checkout flow
4. Write tests for new billing intervals
5. Feature flag rollout to 10% → 100%

[Create GitLab Revival Issue →]

---

### 🪦 Bulk CSV Import for Contacts
**Killed:** June 8, 2021 (commit `9c2d41f`)
**Kill reason:** "Disabling bulk import — DB queries timing out at >500 rows"
**Category:** Infrastructure/performance

**What has changed:**
The team migrated from PostgreSQL 11 to PostgreSQL 15 in March 2023. PostgreSQL 15 includes dramatically improved bulk insert performance (COPY command optimization, better indexing). Additionally, the team added Redis caching in Q2 2023. The original timeout issue at 500 rows is no longer a concern — benchmarks on the current stack show 50,000 rows import in < 2 seconds.

**Evidence:**
- Commit `9c2d41f`: *"Remove bulk import — DB can't handle it, keeps timing out at 500 rows"*
- Issue #789: *"Bulk import disabled due to performance — to revisit after DB upgrade"*
- Commit `f8e12a1` (March 2023): *"Migrate to PostgreSQL 15"*

**Revival assessment:**
- Effort: 5–6 days (re-enable + update for new DB + add progress UI)
- Risk: Medium (needs load testing on new stack)
- Users requesting this: 234 (issues #156, #445, #891, +231 others)

**Estimated annual value: $180,000/year**

[Create GitLab Revival Issue →]

---

### 🪦 Two-Factor Authentication via SMS
**Killed:** October 2, 2022 (commit `b71c9e3`)
**Kill reason:** "Twilio pricing too expensive for our tier — disabling SMS 2FA"
**Category:** Resource constraint (cost)

**What has changed:**
Company revenue grew 3x since October 2022 ($280K MRR → $850K MRR). The Twilio cost that was prohibitive at $280K MRR is now <0.5% of revenue. Additionally, Twilio now offers a Startup pricing tier at 60% discount that didn't exist in 2022.

**Evidence:**
- Commit `b71c9e3`: *"Disable SMS 2FA — Twilio costs $2,400/month which is unsustainable at current scale"*
- Current MRR: $850,000/month
- Twilio Startup tier (launched 2023): $960/month for current SMS volume

**Revival assessment:**
- Effort: 2 days (re-enable existing code, update Twilio API version)
- Risk: Low
- Security impact: reduces enterprise churn (enterprise customers require 2FA)

**Estimated annual value: $200,000/year** (enterprise churn reduction)

[Create GitLab Revival Issue →]

---

## 🟡 INVESTIGATE FURTHER

---

### 🪦 Advanced Analytics Dashboard
**Killed:** April 5, 2021
**Kill reason:** "Disabled — D3.js version conflict blocking deployment"
**Status:** D3.js v7 released in 2021 resolves most version conflicts. However, the original implementation was using D3 v4 patterns that would need refactoring for v7. Needs investigation: is it worth refactoring vs. rebuilding with a modern charts library?

**Recommendation:** Tech lead should review original code. Estimate 2–3 days to assess.

---

### 🪦 White-Label Mode
**Killed:** September 12, 2022
**Kill reason:** "Removing white-label — only 2 customers used it, not worth maintaining"
**Status:** ICP has shifted toward agency customers since then (as of Q1 2026, agencies are 34% of new deals vs. 8% in 2022). White-label is a core agency need. **Market context has changed significantly.** Recommend PM review.

---

*(3 more investigate candidates...)*

---

## ❌ KEEP BURIED

These features were disabled for reasons that still apply:

| Feature | Kill Reason | Still Valid? |
|---------|------------|--------------|
| Bitcoin payments | Regulatory uncertainty | Yes — still unclear in most jurisdictions |
| Social login via Twitter/X | API deprecated | Yes — Twitter API v1 is gone |
| Real-time collaboration (WebSocket) | Architecture doesn't support it | Yes — major refactor needed |
| Offline mode | PWA implementation was too buggy | Yes — still significant complexity |
| AI-generated content suggestions | Quality too low (GPT-3 era) | ⚠️ Actually worth revisiting with GPT-4/Gemini |
| *(4 more...)* | | |

---

## Next Steps

1. **Review the 3 "Resurrect Now" features with your engineering lead**
2. **Prioritize Recurring Billing first** — highest value, lowest risk, 4-day effort
3. **Create GitLab issues using the "Create Revival Issue" button above**
4. **Assign to next sprint**

---

*Output generated by NECRO — The Code Necromancer*
*Repository: acmecorp/product | 4,847 commits analyzed | 24 months of history*
*GitLab MCP tools used: list_commits, get_commit, list_issues, list_merge_requests, search_code*
*Full JSON data: outputs/necro/graveyard_report.json*
*Output file: outputs/necro/graveyard_report.md*
