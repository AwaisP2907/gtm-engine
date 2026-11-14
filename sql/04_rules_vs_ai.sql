-- Where did the AI disagree with the rules-based ranking? (the "AI caught it" cases)
SELECT name, gtm_signal_rank AS rules_rank, gtm_ai_score AS ai_score, gtm_icp_tier AS ai_tier,
       CASE WHEN gtm_signal_rank <= 15 AND gtm_icp_tier IN ('C','DQ') THEN 'AI demoted a top rules pick'
            WHEN gtm_signal_rank > 30 AND gtm_icp_tier = 'A'          THEN 'AI promoted a low rules pick'
       END AS disagreement
FROM hs_companies
WHERE (gtm_signal_rank <= 15 AND gtm_icp_tier IN ('C','DQ'))
   OR (gtm_signal_rank > 30 AND gtm_icp_tier = 'A')
ORDER BY gtm_signal_rank;
