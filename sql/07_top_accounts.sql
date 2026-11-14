-- The rep's worklist: Tier A accounts with owner and best contact.
SELECT c.name, c.gtm_segment AS segment, c.gtm_ai_score AS fit, c.gtm_routing_owner AS owner,
       c.gtm_labor_postings AS labor_postings, c.gtm_sites_hiring AS sites,
       (SELECT p.firstname || ' ' || p.lastname || ' — ' || p.jobtitle FROM hs_contacts p
         WHERE p.gtm_account_key = c.gtm_account_key AND p.gtm_source = 'clay_v1'
         ORDER BY CASE p.gtm_persona WHEN 'champion' THEN 1 WHEN 'economic_buyer' THEN 2 ELSE 3 END LIMIT 1) AS lead_contact
FROM hs_companies c WHERE c.gtm_icp_tier = 'A' ORDER BY fit DESC;
