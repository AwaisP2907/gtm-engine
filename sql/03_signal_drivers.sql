-- Which signals actually separate Tier A from the rest?
SELECT gtm_icp_tier AS tier,
       COUNT(*)                          AS accounts,
       ROUND(AVG(gtm_labor_postings), 1) AS avg_labor_postings,
       ROUND(AVG(gtm_sites_hiring), 1)   AS avg_sites_hiring,
       ROUND(AVG(gtm_automation_postings), 2) AS avg_automation_postings,
       ROUND(AVG(numberofemployees))     AS avg_employees,
       ROUND(AVG(gtm_signal_score), 1)   AS avg_rules_score
FROM hs_companies
WHERE gtm_icp_tier IS NOT NULL
GROUP BY 1
ORDER BY CASE tier WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END;
