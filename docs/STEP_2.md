# Step 2 — Data Hardening

Step 2 strengthens data identity, provenance, availability dates, and provider
reliability before the application adds historical attribution or backtesting.
Yahoo remains the price source while SEC EDGAR becomes the authoritative source
for supported reported fundamentals.

## Milestones

1. **2.1 SEC identity and connection foundation — complete**
   - declared user agent, SEC-host HTTPS restriction, conservative throttling;
   - retries, bounded stale fallback, atomic runtime cache;
   - ticker/CIK/exchange mapping, universe coverage, persisted provider health.
2. **2.2 Filing and availability-date tracking — next**
   - submissions metadata, 10-K/10-Q selection, amendments, acceptance timestamps,
     reporting periods, accession URLs, and deterministic fixtures.
3. **2.3 Company Facts normalization**
   - explicit XBRL concepts, units, fiscal periods, duplicate contexts,
     restatements, missing values, and source provenance.
4. **2.4 Provider integration and comparison**
   - SEC/Yahoo field precedence, transparent fallbacks, coverage and health
     reporting, and old-versus-new ranking comparison.
5. **2.5 Universe-maintenance foundation**
   - listing/CIK joins, eligibility checks, corporate-action handling, and dated
     proposed universe versions before any automatic activation.

Each milestone ends with deterministic tests, a live validation where applicable,
documentation, and a separately reviewable commit.

## Step 2.1 operational command

```powershell
stockrank sec-health
stockrank sec-health --force
```

The default command uses a fresh identity cache when available. `--force` makes
an explicit live request. Both commands compare SEC identities with the configured
universe and save the latest health result for the dashboard. Neither command
changes the universe or ranking.
