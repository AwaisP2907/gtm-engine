-- Pipeline funnel: every stage of the engine, from raw signal to routed alert.
WITH stages AS (
  SELECT 1 AS step, 'Companies with hiring signals (Adzuna, 30d)' AS stage, COUNT(*) AS n FROM raw_signal_companies
  UNION ALL SELECT 2, 'ICP-filtered accounts (no staffing / vendors / IT)', COUNT(*) FROM accounts_ranked
  UNION ALL SELECT 3, 'Top-ranked accounts pushed to HubSpot + enriched', COUNT(*) FROM hs_companies
  UNION ALL SELECT 4, 'AI-scored Tier A or B (worth working)', COUNT(*) FROM hs_companies WHERE gtm_icp_tier IN ('A','B')
  UNION ALL SELECT 5, 'Tier A routed to AE/SDR with Slack alert', COUNT(*) FROM hs_companies
            WHERE gtm_icp_tier = 'A' AND (gtm_routing_owner LIKE 'AE%' OR gtm_routing_owner LIKE 'SDR%')
)
SELECT step, stage, n,
       ROUND(100.0 * n / LAG(n) OVER (ORDER BY step), 1) AS pct_of_prev_stage
FROM stages ORDER BY step;
