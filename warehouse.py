"""
Step 7 — Analytics layer (DuckDB + SQL).

Loads every artifact the engine produces into one local warehouse, runs the
queries in sql/, prints them, and writes data/metrics.json for the dashboard.

Tables
  raw_signal_companies  every company seen in the job-posting pull (pre-filter)
  accounts_ranked       ICP-filtered, rules-scored accounts
  hs_companies          HubSpot snapshot (enrichment, AI tier/score, segment, routing)
  hs_contacts           HubSpot contacts (persona, first-line coverage, reply class)
  ai_run_log            one row per Claude call (latency, tokens, retries, errors)
"""
import glob, json, os
import duckdb

con = duckdb.connect("data/gtm.duckdb")


def load(name, rows):
    con.execute(f"DROP TABLE IF EXISTS {name}")
    path = f"data/_tmp_{name}.json"
    json.dump(rows, open(path, "w"))
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_json_auto('{path}')")
    os.remove(path)


raw = json.load(open("data/adzuna_raw_companies.json"))
load("raw_signal_companies", [dict(zip(
    ["company", "country", "labor_postings", "automation_postings", "locations", "categories", "titles"], r)) for r in raw])
load("accounts_ranked", [{k: v for k, v in a.items() if k != "sample_titles"} for a in json.load(open("data/accounts_ranked.json"))])

snap = json.load(open("data/hubspot_snapshot.json"))
num = {"numberofemployees", "gtm_signal_rank", "gtm_signal_score", "gtm_labor_postings",
       "gtm_automation_postings", "gtm_sites_hiring", "gtm_ai_score"}
companies = [{k: (float(v) if k in num and v not in (None, "") else (v or None)) for k, v in c.items()}
             for c in snap["companies"]]
load("hs_companies", companies)
load("hs_contacts", snap["contacts"])

log = [json.loads(l) for l in open("data/ai_run_log.jsonl")]
for l in log:
    l.setdefault("error", None); l.setdefault("latency_s", None); l.setdefault("in_tok", 0); l.setdefault("out_tok", 0)
load("ai_run_log", log)

metrics = {}
for path in sorted(glob.glob("sql/*.sql")):
    name = os.path.basename(path)[3:-4]
    res = con.execute(open(path).read())
    cols = [d[0] for d in res.description]
    rows = [dict(zip(cols, r)) for r in res.fetchall()]
    metrics[name] = rows
    print(f"\n== {name} ==")
    for r in rows:
        print("  ", r)

metrics["_exported_at"] = snap["exported_at"]
json.dump(metrics, open("data/metrics.json", "w"), indent=1, default=str)
print("\nwrote data/metrics.json")
