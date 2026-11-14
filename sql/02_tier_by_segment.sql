-- Where the opportunity sits: AI tier x company segment, plus routing owner.
SELECT COALESCE(gtm_segment, 'unknown') AS segment,
       COUNT(*) FILTER (WHERE gtm_icp_tier = 'A')  AS tier_a,
       COUNT(*) FILTER (WHERE gtm_icp_tier = 'B')  AS tier_b,
       COUNT(*) FILTER (WHERE gtm_icp_tier = 'C')  AS tier_c,
       COUNT(*) FILTER (WHERE gtm_icp_tier = 'DQ') AS dq,
       COUNT(*) AS total,
       ROUND(AVG(gtm_ai_score), 1) AS avg_fit
FROM hs_companies
GROUP BY 1 ORDER BY total DESC;
