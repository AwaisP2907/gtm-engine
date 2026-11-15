"""
Step 6 — Outbound sequencing (Instantly API v2) + reply webhook.

  python instantly_setup.py campaign   # create the 2-step campaign (created paused)
  python instantly_setup.py leads      # load test leads with AI first lines as {{personalization}}
  python instantly_setup.py webhook    # reply_received -> Make reply-handler webhook
  python instantly_setup.py launch     # activate (sends real email: test inboxes only)

Env: INSTANTLY_API_KEY, INSTANTLY_SENDER, MAKE_REPLY_WEBHOOK, INSTANTLY_CAMPAIGN_ID (after `campaign`)

Brava Robotics is a demo seller, so leads are test inboxes we own, never the real
contacts sourced by Clay. Those stay in HubSpot as the scored, ready-to-work list.

Gotcha found in testing: Instantly strips any body text that isn't wrapped in block
tags. Plain text separated by <br> arrived as a blank email, so every line is a <div>.
"""
import json, os, sys, urllib.request

API = "https://api.instantly.ai/api/v2"
HDR = {"Authorization": f"Bearer {os.environ.get('INSTANTLY_API_KEY', '')}", "Content-Type": "application/json"}


def call(method, path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=HDR)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def html(*lines):
    return "".join(f"<div>{l or '<br>'}</div>" for l in lines)


# Step 1 is one template; the A/B angle and subject come from per-lead custom variables
# (see variants.py), so the variant is assigned in code and attributable in HubSpot.
STEP_1 = html(
    "{{personalization}}", "",
    "{{angle}}", "",
    "I'm with Brava Robotics. We run humanoid robots on a Robot-as-a-Service basis for the repetitive tote "
    "and case moves that keep showing up in material-handler reqs: conveyor-to-conveyor transfers, line-side "
    "replenishment and palletizing support.", "",
    "Most teams start with a 2-3 robot pilot on one lane at one site, measured on hours covered per shift.", "",
    "Worth a 15-minute look at whether one of {{companyName}}'s sites fits?", "",
    "Awais", "Brava Robotics (demo company - GTM Engine portfolio project)")
STEP_2 = html("Bumping this, {{firstName}}. Happy to send a one-page pilot outline for {{companyName}} "
              "instead of a call if that's easier.", "", "Awais")

TEST_LEADS = [  # real Tier-A accounts + AI first lines, delivered to inboxes we control
    {"email": "test-inbox@example.com", "first_name": "[contact]", "company_name": "WESCO", "account_key": "wesco"},
    {"email": "test-inbox@example.com", "first_name": "[contact]", "company_name": "Performance Foodservice",
     "account_key": "performance-foodservice"},
    {"email": "test-inbox@example.com", "first_name": "[contact]", "company_name": "Ryder",
     "account_key": "ryder-system-inc"},
]


def campaign():
    days = {str(i): True for i in range(7)}
    c = call("POST", "/campaigns", {
        "name": "Brava - Labor-signal pilot (DEMO, test inboxes only)",
        "campaign_schedule": {"schedules": [{"name": "All week", "timing": {"from": "00:00", "to": "23:59"},
                                             "days": days, "timezone": "America/Detroit"}]},
        "sequences": [{"steps": [
            {"type": "email", "delay": 2, "variants": [{"subject": "{{subject_line}}", "body": STEP_1}]},
            {"type": "email", "delay": 0, "variants": [{"subject": "", "body": STEP_2}]}]}],
        "email_list": [os.environ["INSTANTLY_SENDER"]], "daily_limit": 10,
        "stop_on_reply": True, "link_tracking": False, "open_tracking": False})
    print("campaign id:", c["id"])


def leads():
    from variants import VARIANTS
    assigned = {v["account_key"]: v["variant"] for v in json.load(open("data/copy_variants.json")).values()}
    scored = json.load(open("data/ai_scored.json"))
    hs = {c["gtm_account_key"]: c["id"] for c in json.load(open("data/hubspot_snapshot.json"))["companies"]}
    for l in TEST_LEADS:
        lines = scored[l["account_key"]].get("first_lines", {})
        first_line = next((v for k, v in lines.items() if k.startswith(l["first_name"])), "")
        call("POST", "/leads", {
            "email": l["email"], "first_name": l["first_name"], "last_name": "(test)",
            "company_name": l["company_name"], "personalization": first_line,
            "custom_variables": {"hubspot_company_id": hs[l["account_key"]], "account_key": l["account_key"],
                                 "copy_variant": assigned[l["account_key"]],
                                 "angle": VARIANTS[assigned[l["account_key"]]]["angle"],
                                 "subject_line": VARIANTS[assigned[l["account_key"]]]["subject"].replace(
                                     "{{companyName}}", l["company_name"])},
            "campaign": os.environ["INSTANTLY_CAMPAIGN_ID"]})
    print(f"loaded {len(TEST_LEADS)} leads")


def webhook():
    w = call("POST", "/webhooks", {"name": "GTM Engine reply handler (Make)", "event_type": "reply_received",
                                   "target_hook_url": os.environ["MAKE_REPLY_WEBHOOK"],
                                   "campaign": os.environ["INSTANTLY_CAMPAIGN_ID"]})
    print("webhook id:", w["id"])


def launch():
    call("POST", f"/campaigns/{os.environ['INSTANTLY_CAMPAIGN_ID']}/activate", {})
    print("campaign active")


if __name__ == "__main__":
    {"campaign": campaign, "leads": leads, "webhook": webhook, "launch": launch}[sys.argv[1]]()
