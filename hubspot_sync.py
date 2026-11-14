"""
Step 2/3/4 — HubSpot as the system of record.

  python hubspot_sync.py schema     # create property groups + custom properties (idempotent)
  python hubspot_sync.py accounts   # upsert ranked accounts (dedupe key: gtm_account_key)
  python hubspot_sync.py enrich     # write Clay firmographics + contacts, associate contact->company
  python hubspot_sync.py ai         # write AI tier/score/reasoning/brief + per-contact first lines
  python hubspot_sync.py segment    # derive Enterprise / Mid-Market / SMB from headcount
  python hubspot_sync.py route      # send every scored account to the Make routing webhook
  python hubspot_sync.py snapshot   # export companies + contacts for the SQL warehouse

Env: HUBSPOT_TOKEN (service key), MAKE_ROUTE_WEBHOOK
All writes are batch upserts on a unique custom key, so re-running never creates duplicates.
"""
import json, os, re, sys, time, urllib.request, urllib.error

API = "https://api.hubapi.com"
TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def call(method, path, body=None, retries=3):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(API + path, data=data, method=method, headers=HDR)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:          # rate limit / transient -> back off
                time.sleep(2 ** attempt); continue
            if e.code == 409:                            # property/group already exists
                return {"exists": True}
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")
    raise RuntimeError(f"{method} {path} failed after {retries} retries")


def batches(rows, n=100):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def P(name, label, type_, field, **extra):
    return {"name": name, "label": label, "type": type_, "fieldType": field, "groupName": "gtm_engine", **extra}


def opts(pairs):
    return [{"label": l, "value": v, "displayOrder": i} for i, (l, v) in enumerate(pairs)]


COMPANY_PROPS = [
    P("gtm_account_key", "GTM Account Key", "string", "text", hasUniqueValue=True),
    P("gtm_source", "GTM Source", "string", "text"),
    P("gtm_signal_rank", "Signal Rank", "number", "number"),
    P("gtm_signal_score", "Signal Score", "number", "number"),
    P("gtm_labor_postings", "Material-Handling Postings (30d)", "number", "number"),
    P("gtm_automation_postings", "Industrial Automation Postings (30d)", "number", "number"),
    P("gtm_sites_hiring", "Sites Hiring", "number", "number"),
    P("gtm_sample_titles", "Sample Job Titles", "string", "textarea"),
    P("gtm_signal_date", "Signal Date", "date", "date"),
    P("gtm_industry", "Industry (Clay)", "string", "text"),
    P("gtm_company_size", "Company Size Band (Clay)", "string", "text"),
    P("gtm_revenue_band", "Revenue Band (Clay)", "string", "text"),
    P("gtm_hq", "HQ (Clay)", "string", "text"),
    P("gtm_icp_tier", "ICP Tier", "enumeration", "select",
      options=opts([("Tier A", "A"), ("Tier B", "B"), ("Tier C", "C"), ("Disqualified", "DQ")])),
    P("gtm_segment", "Segment", "enumeration", "select",
      options=opts([("Enterprise (10k+)", "enterprise"), ("Mid-Market (1k-10k)", "mid_market"),
                    ("SMB (<1k)", "smb"), ("Unknown", "unknown")])),
    P("gtm_ai_score", "AI Fit Score", "number", "number"),
    P("gtm_ai_reasoning", "AI Reasoning", "string", "textarea"),
    P("gtm_ai_brief", "AI Account Brief", "string", "textarea"),
    P("gtm_first_line", "AI First Line", "string", "textarea"),
    P("gtm_routing_owner", "Routed To", "string", "text"),
    P("gtm_engine_status", "Engine Status", "enumeration", "select",
      options=opts([(s, s) for s in ["ingested", "enriched", "scored", "routed", "sequenced", "replied", "error"]])),
]
CONTACT_PROPS = [
    P("gtm_contact_key", "GTM Contact Key", "string", "text", hasUniqueValue=True),
    P("gtm_account_key", "GTM Account Key", "string", "text"),
    P("gtm_location", "GTM Location", "string", "text"),
    P("gtm_source", "GTM Source", "string", "text"),
    P("gtm_persona", "Buyer Persona", "enumeration", "select",
      options=opts([("Economic Buyer", "economic_buyer"), ("Champion", "champion"), ("Operator", "operator")])),
    P("gtm_first_line", "AI First Line", "string", "textarea"),
    P("gtm_reply_class", "AI Reply Classification", "enumeration", "select",
      options=opts([(s, s) for s in ["interested", "objection", "not_now", "wrong_person", "unsubscribe", "out_of_office"]])),
]


def key_of(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def persona(title):
    t = title.lower()
    if re.search(r"\b(vp|vice president|svp|evp)\b", t):
        return "economic_buyer"
    return "champion" if "director" in t else "operator"


def schema():
    for obj, props in (("companies", COMPANY_PROPS), ("contacts", CONTACT_PROPS)):
        call("POST", f"/crm/v3/properties/{obj}/groups",
             {"name": "gtm_engine", "label": "GTM Engine (Brava Robotics demo)"})
        for p in props:
            call("POST", f"/crm/v3/properties/{obj}", p)
    print("schema ok")


def accounts(top=50):
    rows = json.load(open("data/accounts_ranked.json"))[:top]
    inputs = [{"idProperty": "gtm_account_key", "id": key_of(a["company"]), "properties": {
        "name": a["company"], "gtm_account_key": key_of(a["company"]), "gtm_source": "adzuna_jobs_v1",
        "gtm_signal_rank": a["rank"], "gtm_signal_score": a["signal_score"],
        "gtm_labor_postings": a["labor_postings"], "gtm_automation_postings": a["industrial_automation_postings"],
        "gtm_sites_hiring": a["sites_hiring"], "gtm_sample_titles": "; ".join(a["sample_titles"]),
        "gtm_engine_status": "ingested"}} for a in rows]
    for b in batches(inputs):
        call("POST", "/crm/v3/objects/companies/batch/upsert", {"inputs": b})
    print(f"upserted {len(inputs)} accounts")


def enrich():
    d = json.load(open("data/clay_enrichment.json"))
    cos = [{"idProperty": "gtm_account_key", "id": k, "properties": {
        "domain": v["domain"], "gtm_industry": v["industry"], "numberofemployees": v["employees"],
        "gtm_company_size": v["size"], "gtm_revenue_band": v["revenue_band"], "gtm_hq": v["hq"],
        "gtm_engine_status": "enriched"}} for k, v in d["companies"].items()]
    res = []
    for b in batches(cos):
        res += call("POST", "/crm/v3/objects/companies/batch/upsert", {"inputs": b})["results"]
    co_id = {r["properties"]["gtm_account_key"]: r["id"] for r in res}
    cts = []
    for acct, name, title, loc, url in d["contacts"]:
        first, last = name.split(" ", 1)
        key = url.rstrip("/").split("/")[-1]
        cts.append({"idProperty": "gtm_contact_key", "id": key, "properties": {
            "firstname": first, "lastname": last, "jobtitle": title, "gtm_contact_key": key,
            "hs_linkedin_url": url, "gtm_location": loc, "gtm_persona": persona(title),
            "gtm_account_key": acct, "gtm_source": "clay_v1"}})
    created = []
    for b in batches(cts):
        created += call("POST", "/crm/v3/objects/contacts/batch/upsert", {"inputs": b})["results"]
    assoc = [{"from": {"id": c["id"]}, "to": {"id": co_id[c["properties"]["gtm_account_key"]]}}
             for c in created if c["properties"].get("gtm_account_key") in co_id]
    for b in batches(assoc):
        call("POST", "/crm/v4/associations/contacts/companies/batch/associate/default", {"inputs": b})
    print(f"enriched {len(cos)} companies, {len(created)} contacts, {len(assoc)} associations")


def ai():
    scored = json.load(open("data/ai_scored.json"))
    enr = json.load(open("data/clay_enrichment.json"))
    name2key = {c[1]: c[4].rstrip("/").split("/")[-1] for c in enr["contacts"]}
    cos, lines = [], []
    for k, v in scored.items():
        if "tier" not in v:
            continue
        cos.append({"idProperty": "gtm_account_key", "id": k, "properties": {
            "gtm_ai_score": v["fit_score"], "gtm_icp_tier": v["tier"], "gtm_ai_reasoning": v["reasoning"],
            "gtm_ai_brief": "\n".join("• " + b for b in v.get("brief", [])), "gtm_engine_status": "scored"}})
        for name, line in (v.get("first_lines") or {}).items():
            if name in name2key:
                lines.append({"idProperty": "gtm_contact_key", "id": name2key[name],
                              "properties": {"gtm_first_line": line}})
    for b in batches(cos):
        call("POST", "/crm/v3/objects/companies/batch/upsert", {"inputs": b})
    for b in batches(lines):
        call("POST", "/crm/v3/objects/contacts/batch/upsert", {"inputs": b})
    print(f"wrote AI fields to {len(cos)} companies, {len(lines)} first lines")


def search_all(obj, filters, props):
    out, after = [], None
    while True:
        body = {"filterGroups": filters, "properties": props, "limit": 100}
        if after:
            body["after"] = after
        r = call("POST", f"/crm/v3/objects/{obj}/search", body)
        out += [{"id": x["id"], **x["properties"]} for x in r["results"]]
        after = r.get("paging", {}).get("next", {}).get("after")
        if not after:
            return out


SRC = [{"filters": [{"propertyName": "gtm_source", "operator": "EQ", "value": "adzuna_jobs_v1"}]}]


def segment():
    rows = search_all("companies", SRC, ["numberofemployees", "gtm_company_size"])

    def seg(c):
        band, n = c.get("gtm_company_size") or "", float(c.get("numberofemployees") or 0)
        if band.startswith("10,001") or n >= 10000: return "enterprise"
        if band.startswith(("1,001", "5,001")) or n >= 1000: return "mid_market"
        return "smb" if (n or band) else "unknown"
    inputs = [{"id": c["id"], "properties": {"gtm_segment": seg(c)}} for c in rows]
    for b in batches(inputs):
        call("POST", "/crm/v3/objects/companies/batch/update", {"inputs": b})
    print(f"segmented {len(inputs)} companies")


def route():
    """Send each scored account to Make. Free-text fields are pre-escaped so Make can drop
    them straight into the Slack JSON body without breaking it."""
    portal = call("GET", "/account-info/v3/details")["portalId"]
    hook = os.environ["MAKE_ROUTE_WEBHOOK"]
    esc = lambda s: json.dumps(s or "")[1:-1]
    cos = search_all("companies", SRC, ["name", "gtm_account_key", "gtm_icp_tier", "gtm_ai_score", "gtm_segment",
                                        "gtm_ai_reasoning", "gtm_ai_brief"])
    cts = search_all("contacts", [{"filters": [{"propertyName": "gtm_source", "operator": "EQ", "value": "clay_v1"}]}],
                     ["firstname", "lastname", "jobtitle", "gtm_account_key", "gtm_persona", "gtm_first_line"])
    rank = {"champion": 0, "economic_buyer": 1, "operator": 2}
    for c in cos:
        people = sorted([p for p in cts if p.get("gtm_account_key") == c["gtm_account_key"]],
                        key=lambda p: rank.get(p.get("gtm_persona"), 3))
        lead = people[0] if people else None
        payload = {
            "account_key": c["gtm_account_key"], "hubspot_id": c["id"], "company": c["name"],
            "tier": c["gtm_icp_tier"], "score": c["gtm_ai_score"], "segment": c["gtm_segment"],
            "reasoning_esc": esc(c["gtm_ai_reasoning"]), "brief_esc": esc(c["gtm_ai_brief"]),
            "contact_esc": esc(f"{lead['firstname']} {lead['lastname']}, {lead['jobtitle']}" if lead else "none found"),
            "first_line_esc": esc(lead.get("gtm_first_line") if lead else ""),
            "hubspot_url": f"https://app.hubspot.com/contacts/{portal}/record/0-2/{c['id']}"}
        req = urllib.request.Request(hook, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        time.sleep(0.7)   # stay well under Make's webhook rate limit
    print(f"routed {len(cos)} accounts")


def snapshot():
    cos = search_all("companies", SRC, ["name", "gtm_account_key", "domain", "gtm_industry", "numberofemployees",
                                        "gtm_segment", "gtm_signal_rank", "gtm_signal_score", "gtm_labor_postings",
                                        "gtm_automation_postings", "gtm_sites_hiring", "gtm_icp_tier", "gtm_ai_score",
                                        "gtm_engine_status", "gtm_routing_owner", "country"])
    cts = search_all("contacts", [{"filters": [{"propertyName": "gtm_source", "operator": "EQ", "value": s}]}
                                  for s in ("clay_v1", "test_seed")],
                     ["firstname", "lastname", "jobtitle", "email", "gtm_account_key", "gtm_persona", "gtm_source",
                      "gtm_first_line", "gtm_reply_class"])
    for c in cts:
        c["has_first_line"] = bool(c.pop("gtm_first_line", None))
    json.dump({"exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "companies": cos, "contacts": cts},
              open("data/hubspot_snapshot.json", "w"), indent=1)
    print(f"snapshot: {len(cos)} companies, {len(cts)} contacts")


if __name__ == "__main__":
    {"schema": schema, "accounts": accounts, "enrich": enrich, "ai": ai, "segment": segment,
     "route": route, "snapshot": snapshot}[sys.argv[1]]()
