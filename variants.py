"""
Copy variant testing: which opening angle gets more replies, per segment.

    python variants.py            -> writes data/copy_variants.json (assignment for every contact)

Two angles for email step 1. Both open with the AI-written first line; they differ in the
paragraph that follows it (the "angle") and in the subject line.

  A_signal  leads with the hiring signal we detected   ("19 material handler postings across 9 sites")
  B_cost    leads with the cost of the labor gap        (overtime, temp agency premiums, missed cut-offs)

Assignment is done here, not by Instantly's random split, for two reasons:
  1. Stratified: contacts are alternated A/B *within* each segment x tier bucket, so the two arms see
     the same mix of enterprise/mid-market and Tier A/B accounts. A random split on ~60 contacts can
     easily put most Tier A accounts in one arm and "win" for the wrong reason.
  2. Attributable: the variant is written to the HubSpot contact (gtm_copy_variant) and to the
     Instantly lead (custom variable), so replies, reply class and deals join back to the copy that
     produced them in SQL (sql/08_copy_variant_test.sql).

Contacts at the same account always get the same variant, so one company never sees both angles.
"""
import json
from collections import defaultdict

VARIANTS = {
    "A_signal": {
        "subject": "{{companyName}}'s material handler hiring",
        "angle": ("Reason I'm reaching out: your team is hiring for the same repetitive tote and case moves "
                  "at several sites at once, which is exactly the work our humanoids pick up first."),
    },
    "B_cost": {
        "subject": "cost of open material handler shifts at {{companyName}}",
        "angle": ("Reason I'm reaching out: every unfilled material handler shift usually turns into overtime "
                  "or temp-agency premiums, and those moves are exactly the work our humanoids pick up first."),
    },
}
ARMS = list(VARIANTS)

# Below this many sends per arm, a reply-rate difference is noise (cold email reply rates of 1-5%
# need a few hundred sends per arm to separate). The dashboard shows the test as "collecting".
MIN_SENDS_PER_ARM = 200


def assign(snapshot):
    """Return {contact_id: {"account_key", "variant", "bucket"}} with accounts alternated A/B per bucket."""
    companies = {c["gtm_account_key"]: c for c in snapshot["companies"]}
    contacts = [c for c in snapshot["contacts"] if c.get("gtm_account_key") in companies]

    buckets = defaultdict(list)
    for key in sorted({c["gtm_account_key"] for c in contacts}):
        co = companies[key]
        buckets[(co.get("gtm_segment") or "unknown", co.get("gtm_icp_tier") or "unscored")].append(key)

    account_variant = {}
    for bucket, keys in sorted(buckets.items()):
        for i, key in enumerate(keys):
            account_variant[key] = (ARMS[i % 2], f"{bucket[0]} / Tier {bucket[1]}")

    return {c["id"]: {"account_key": c["gtm_account_key"],
                      "variant": account_variant[c["gtm_account_key"]][0],
                      "bucket": account_variant[c["gtm_account_key"]][1]}
            for c in contacts}


if __name__ == "__main__":
    snap = json.load(open("data/hubspot_snapshot.json"))
    out = assign(snap)
    json.dump(out, open("data/copy_variants.json", "w"), indent=1)
    from collections import Counter
    print(Counter(v["variant"] for v in out.values()))
    print(Counter((v["bucket"], v["variant"]) for v in out.values()))
