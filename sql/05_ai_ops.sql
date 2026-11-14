-- AI layer reliability: calls, failures, retries, latency, tokens.
SELECT COUNT(*)                                         AS calls_logged,
       COUNT(*) FILTER (WHERE error IS NOT NULL)        AS failed_calls,
       ROUND(100.0 * COUNT(*) FILTER (WHERE error IS NOT NULL) / COUNT(*), 1) AS failure_rate_pct,
       COUNT(*) FILTER (WHERE attempt > 1 AND error IS NULL) AS succeeded_after_retry,
       ROUND(AVG(latency_s) FILTER (WHERE error IS NULL), 2)  AS avg_latency_s,
       SUM(in_tok)  AS input_tokens,
       SUM(out_tok) AS output_tokens
FROM ai_run_log;
