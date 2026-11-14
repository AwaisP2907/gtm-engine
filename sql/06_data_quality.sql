-- Data-quality checks a GTM engineer runs before anything goes to reps.
SELECT 'Accounts missing firmographics' AS check_name, COUNT(*) AS n FROM hs_companies WHERE domain IS NULL
UNION ALL SELECT 'Accounts with no buyer contact',
  COUNT(*) FROM hs_companies c WHERE NOT EXISTS (SELECT 1 FROM hs_contacts p WHERE p.gtm_account_key = c.gtm_account_key AND p.gtm_source = 'clay_v1')
UNION ALL SELECT 'Duplicate account keys', COUNT(*) - COUNT(DISTINCT gtm_account_key) FROM hs_companies
UNION ALL SELECT 'Duplicate contacts (same name + account)',
  COUNT(*) - COUNT(DISTINCT firstname || lastname || gtm_account_key) FROM hs_contacts WHERE gtm_source = 'clay_v1'
UNION ALL SELECT 'Contacts missing AI first line', COUNT(*) FROM hs_contacts WHERE gtm_source = 'clay_v1' AND NOT has_first_line
UNION ALL SELECT 'Likely wrong-entity matches (AI DQ)', COUNT(*) FROM hs_companies WHERE gtm_icp_tier = 'DQ'
UNION ALL SELECT 'Contacts by persona: economic buyer', COUNT(*) FROM hs_contacts WHERE gtm_source='clay_v1' AND gtm_persona='economic_buyer'
UNION ALL SELECT 'Contacts by persona: champion',       COUNT(*) FROM hs_contacts WHERE gtm_source='clay_v1' AND gtm_persona='champion'
UNION ALL SELECT 'Contacts by persona: operator',       COUNT(*) FROM hs_contacts WHERE gtm_source='clay_v1' AND gtm_persona='operator';
