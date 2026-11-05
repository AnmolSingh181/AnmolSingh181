# Known limitations & future improvements

## Limitations (current MVP)
- **No live data yet.** The database ships empty. Live external calls could not be executed from the build
  environment (network policy), so connectors for US Census, UN Comtrade, search APIs, Apollo, ZeroBounce and OpenAI
  are untested against the live services. Run each once after deployment and review the job log.
- **Commercial trade data** (ImportYeti, Volza, Panjiva, TradeData.Pro, Kompass) requires your exports or contracts.
  CSV column auto-mapping uses common header synonyms; confirm the mapping on the first file (the job log prints it) and
  pass an explicit `mapping` if needed.
- **Directories** are disabled until their terms are reviewed and selectors configured per site.
- **Rule classifier** is English-centric (plus PE-LD style notation). Chinese/Vietnamese/Arabic pages rely on English
  sections or AI mode. Long, unstructured pages can produce `unknown` relationships: by design, they need review.
- **Individual contacts** are extracted only when a page explicitly pairs a name with a title and a channel. Many sites
  publish only general emails. Decision-maker status is title-based ("likely") until manually confirmed.
- **Email deliverability**: without ZeroBounce the highest automatic status is `domain_checked` (MX).
- **Entity resolution** is conservative: expect a review queue rather than silent merges. Group companies sharing a
  domain are flagged, not merged.
- **CSV imports run synchronously** in the request (≤ 20 MB). Very large files should be split or run with
  `python -m app.cli import-file`.
- **Scheduler intervals** are read at worker start; restart the worker after changing them.
- **Supabase Auth** mode is supported by the API; the bundled login page uses local auth.
- **Lead score** is a heuristic prioritisation, not a conversion probability.
- **Market prices are not tick-by-tick.** Free official sources are daily (DCE settlements, crude/gas, FX) or monthly
  (US PPI indices). Indian producer prices and physical import/export assessments need manual entry, CSV import or a
  paid feed. FRED and DCE connectors are untested against the live services (network blocked in the build env).

## Future improvements
1. Background processing for large imports (queue file to Supabase Storage + worker job).
2. Multilingual dictionary entries (CN/VN/AR/TR) and per-country search terms in discovery queries.
3. Company-level customs datasets where legally available (e.g. US bill-of-lading via licensed provider).
4. Fuller Supabase Auth UI (magic link / SSO) and team-shared leads.
5. Metabase on the same Postgres for ad-hoc analytics; scheduled email digests.
6. Trade-statistics trend charts; implied unit values (USD/t) from `trade_statistics` as an extra price signal.
7. More free price sources: India WPI (Office of the Economic Adviser), ZCE/SHFE contracts, DCE night session.
7. Expand markets: activate Turkey, Thailand, Malaysia, Indonesia, Korea, Germany, Netherlands in Settings.
8. Embedding-based similarity for duplicate suggestions and semantic search.
