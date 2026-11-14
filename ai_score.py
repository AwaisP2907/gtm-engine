"""
Step 3 — AI scoring + research layer (Claude API).

For each account: fit score (0-100), ICP tier (A/B/C/DQ), reasoning, a 3-bullet
account brief for the rep, and a personalized first line for every buyer contact.

Input : data/accounts_ranked.json (signals) + data/clay_enrichment.json (firmographics, contacts)
Output: data/ai_scored.json  +  data/ai_run_log.jsonl (one line per call: latency, tokens, errors)
"""
import json, os, re, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

MODEL = "claude-haiku-5-5"
API = "https://api.anthropic.com/v1/messages"
KEY = os.environ["ANTHROPIC_API_KEY"]
MAX_RETRIES = 3

SELLER = """You are the GTM research analyst for Brava Robotics (a demo seller), a humanoid-robot
Robot-as-a-Service (RaaS) company. Brava's humanoids handle repetitive tote and case movement —
picking, transferring totes between conveyors, palletizing support, line-side replenishment —
in warehouses, distribution centers and plants. Pricing is roughly $10-30K per robot per year;
deals start as a 2-5 robot pilot at one site and expand across the network.

Ideal customer profile:
- North American operator running distribution centers, 3PL warehouses or manufacturing plants
- High-volume, repetitive tote/case/material handling done by people today
- Persistent hourly-labor hiring (material handlers, pickers, forklift operators) across multiple sites
- Bonus: hiring automation/controls engineers or already running AMRs/conveyors (automation-ready)
Disqualify: staffing agencies, IT/services firms, companies with no real warehouse/plant operation,
retail store-floor-only roles, wrong-entity matches (enrichment data clearly about a different company).

Tiers: A = strong fit, pursue now; B = good fit, nurture; C = weak fit; DQ = disqualified."""

INSTRUCTIONS = """Score this account and write outreach. Return ONLY a JSON object:
{
 "fit_score": <0-100 integer>,
 "tier": "A" | "B" | "C" | "DQ",
 "reasoning": "<2 sentences: why this score, citing the specific signals>",
 "brief": ["<bullet 1: what they run / where the labor pain is>", "<bullet 2: the signal and why now>", "<bullet 3: suggested pilot angle>"],
 "first_lines": {"<contact full name>": "<one personalized opening sentence, max 30 words, referencing their role and the hiring signal; no flattery, no 'I hope this finds you well'>"}
}
If tier is DQ, first_lines must be {}."""


def call_claude(prompt):
    body = json.dumps({"model": MODEL, "max_tokens": 2500, "system": SELLER,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            parsed = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            return parsed, {"attempt": attempt, "latency_s": round(time.time() - t0, 2),
                            "in_tok": data["usage"]["input_tokens"], "out_tok": data["usage"]["output_tokens"]}
        except (urllib.error.URLError, AttributeError, json.JSONDecodeError, KeyError) as e:
            err = str(e)
            time.sleep(2 ** attempt)  # exponential backoff
    return None, {"attempt": MAX_RETRIES, "error": err}


def build_prompt(acct, firmo, contacts):
    lines = [f"Company: {acct['company']} ({acct['country']})"]
    if firmo:
        lines.append(f"Firmographics (Clay): industry={firmo['industry']}; employees={firmo['employees']}; "
                     f"size band={firmo['size']}; revenue={firmo['revenue_band']}; HQ={firmo['hq']}; domain={firmo['domain']}")
        if firmo.get("_note"):
            lines.append(f"Data note: {firmo['_note']}")
    else:
        lines.append("Firmographics: not found in Clay (enrichment miss).")
    lines.append(f"Hiring signals (last 30 days, job postings API): {acct['labor_postings']} material-handling "
                 f"postings across {acct['sites_hiring']} sites; {acct['industrial_automation_postings']} industrial "
                 f"automation/controls postings. Sample titles: {'; '.join(acct['sample_titles'])}")
    lines.append(f"Rules-based signal score: {acct['signal_score']} (rank {acct['rank']} of 440)")
    if contacts:
        lines.append("Buyer contacts: " + "; ".join(f"{c[1]} — {c[2]} ({c[3]})" for c in contacts))
    else:
        lines.append("Buyer contacts: none found.")
    return "\n".join(lines) + "\n\n" + INSTRUCTIONS


def key_of(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    accounts = json.load(open("data/accounts_ranked.json"))[:50]
    enr = json.load(open("data/clay_enrichment.json"))
    by_acct = {}
    for c in enr["contacts"]:
        by_acct.setdefault(c[0], []).append(c)

    def work(acct):
        k = key_of(acct["company"])
        result, meta = call_claude(build_prompt(acct, enr["companies"].get(k), by_acct.get(k, [])))
        return k, acct["company"], result, meta

    # Resume: only (re)run accounts without a successful result — failed calls are retried, good ones aren't re-billed.
    prev = json.load(open("data/ai_scored.json")) if os.path.exists("data/ai_scored.json") else {}
    todo = [a for a in accounts if "tier" not in prev.get(key_of(a["company"]), {})]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(work, todo))

    out, log = dict(prev), open("data/ai_run_log.jsonl", "a")
    tin = tout = 0
    for k, name, res, meta in results:
        log.write(json.dumps({"account": k, **meta}) + "\n")
        tin += meta.get("in_tok", 0); tout += meta.get("out_tok", 0)
        out[k] = {"company": name, **(res or {"error": meta.get("error")})}
    json.dump(out, open("data/ai_scored.json", "w"), indent=1)
    tiers = {}
    for v in out.values():
        tiers[v.get("tier", "ERR")] = tiers.get(v.get("tier", "ERR"), 0) + 1
    print("tiers:", tiers, "| tokens in/out:", tin, tout)


if __name__ == "__main__":
    main()
