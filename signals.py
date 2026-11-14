"""
Step 1 — Signal ingestion + account ranking.

Input : data/adzuna_raw_companies.json  (job postings pulled from the Adzuna API,
        grouped by company: [name, country, labor_posts, automation_posts,
        distinct_locations, categories, titles])
Output: data/accounts_ranked.json + data/accounts_top50.csv

ICP: North American operators with high-volume tote / material handling
(3PLs, distribution, manufacturing) — buyers for a humanoid Robot-as-a-Service product.

Signals scored:
  labor_pain      – volume of material-handler / picker / forklift postings (log-scaled)
  footprint       – number of distinct sites hiring (multi-site = bigger deployment)
  automation_ready– industrial controls / automation / robotics engineer postings
  combo           – both labor pain AND automation hiring at the same company
"""
import csv, json, math, re
from collections import defaultdict

RAW = "data/adzuna_raw_companies.json"

# Staffing agencies post on behalf of others — not buyers.
STAFFING = re.compile(
    r"staff|personnel|labor ready|workforce|recruit|talent|employment|temp\b|agency|"
    r"manpower|adecco|randstad|kelly|aerotek|insight global|robert half|express emp|"
    r"spherion|volt|tekgroup|actalent|jobot|apex systems|tandym|cynet|employal|fuze hr|"
    r"recutify|acara|brunel|morson|it associates|hr solutions|jobs\b|careers|people ?store|"
    r"peopleready|abacus service",
    re.I,
)
# Robotics/automation vendors and consultancies are competitors or partners, not buyers.
NOT_BUYER = re.compile(
    r"robot|humanoid|automation\b|accenture|stantec|jacobs|booz allen|bba consult|"
    r"associated engineering|vista projects|govcio|ust\b|circuit stream|anduril|valknut|"
    r"worley|atkinsr|thermon",
    re.I,
)
SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|company|system|systems|holdings|group|"
    r"canada|usa|us|ground|foodservice|food group|communications|the)\b|[.,&']",
    re.I,
)


def norm(name: str) -> str:
    n = name.lower().replace("é", "e").replace("nestl ", "nestle ")
    n = SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def load():
    merged = defaultdict(lambda: {"names": set(), "countries": set(), "labor": 0,
                                  "auto_industrial": 0, "auto_it": 0, "locs": 0,
                                  "titles": set()})
    for name, country, labor, auto, locs, cats, titles in json.load(open(RAW)):
        if STAFFING.search(name) or NOT_BUYER.search(name):
            continue
        m = merged[norm(name)]
        m["names"].add(name)
        m["countries"].add(country.upper())
        m["labor"] += labor
        m["locs"] += locs
        # Automation posts in IT categories are QA/DevOps — not industrial automation.
        if "IT Jobs" in cats and "Engineering" not in cats:
            m["auto_it"] += auto
        else:
            m["auto_industrial"] += auto
        m["titles"].update(t.strip() for t in titles.split("|") if t.strip())
    return merged


def score(a):
    labor_pain = min(40, 12 * math.log1p(a["labor"]))
    footprint = min(25, 9 * math.log1p(a["locs"]))
    automation_ready = min(20, 10 * math.log1p(a["auto_industrial"])) * min(1, a["labor"] / 3)
    combo = 15 if a["labor"] >= 3 and a["auto_industrial"] > 0 else 0
    return round(labor_pain + footprint + automation_ready + combo, 1), {
        "labor_pain": round(labor_pain, 1), "footprint": round(footprint, 1),
        "automation_ready": round(automation_ready, 1), "combo": combo}


def main():
    accounts = []
    for key, a in load().items():
        if a["labor"] == 0:  # ICP requires material-handling volume
            continue
        s, parts = score(a)
        name = max(a["names"], key=len)
        accounts.append({
            "company": name, "country": "/".join(sorted(a["countries"])),
            "labor_postings": a["labor"], "industrial_automation_postings": a["auto_industrial"],
            "sites_hiring": a["locs"], "signal_score": s, **parts,
            "sample_titles": sorted(a["titles"])[:4],
        })
    accounts.sort(key=lambda x: -x["signal_score"])
    for i, a in enumerate(accounts, 1):
        a["rank"] = i
    json.dump(accounts, open("data/accounts_ranked.json", "w"), indent=1)
    with open("data/accounts_top50.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "company", "country", "signal_score", "labor_postings",
                    "industrial_automation_postings", "sites_hiring", "sample_titles"])
        for a in accounts[:50]:
            w.writerow([a["rank"], a["company"], a["country"], a["signal_score"],
                        a["labor_postings"], a["industrial_automation_postings"],
                        a["sites_hiring"], "; ".join(a["sample_titles"])])
    print(f"{len(accounts)} ICP accounts scored; top 50 written.")
    for a in accounts[:50]:
        print(f'{a["rank"]:>2}. {a["company"][:38]:<38} {a["country"]:<5} score {a["signal_score"]:>5}  '
              f'labor {a["labor_postings"]:>3}  auto {a["industrial_automation_postings"]}  sites {a["sites_hiring"]}')


if __name__ == "__main__":
    main()
