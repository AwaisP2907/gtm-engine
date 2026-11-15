-- Copy variant test: is the split balanced, and which opening angle earns more replies?
-- Balance columns are readable now; result columns fill in once sends carry a variant.
WITH arms AS (
  SELECT v.variant,
         COUNT(*)                                             AS contacts,
         COUNT(DISTINCT v.account_key)                        AS accounts,
         ROUND(100.0 * AVG(CASE WHEN c.gtm_icp_tier = 'A' THEN 1 ELSE 0 END), 0) AS pct_tier_a,
         ROUND(100.0 * AVG(CASE WHEN c.gtm_segment = 'enterprise' THEN 1 ELSE 0 END), 0) AS pct_enterprise
  FROM copy_variants v JOIN hs_companies c ON c.gtm_account_key = v.account_key
  GROUP BY v.variant
), results AS (
  SELECT s.variant,
         COUNT(*)                                                      AS sends,
         COUNT(*) FILTER (WHERE s.replied)                             AS replies,
         COUNT(*) FILTER (WHERE s.reply_class = 'interested')          AS interested
  FROM variant_sends s GROUP BY s.variant
)
SELECT a.variant, a.contacts, a.accounts, a.pct_tier_a, a.pct_enterprise,
       COALESCE(r.sends, 0)      AS sends,
       COALESCE(r.replies, 0)    AS replies,
       COALESCE(r.interested, 0) AS interested,
       CASE WHEN COALESCE(r.sends, 0) = 0 THEN NULL
            ELSE ROUND(100.0 * r.replies / r.sends, 1) END AS reply_rate_pct,
       CASE WHEN COALESCE(r.sends, 0) < 200 THEN 'collecting (needs 200 sends per arm)'
            ELSE 'readable' END AS status
FROM arms a LEFT JOIN results r USING (variant)
ORDER BY a.variant;
