"""
Generate the two Make.com scenario blueprints that run the GTM Engine's automation layer.

    python make/build_blueprints.py      -> writes make/*.blueprint.json

Import each JSON in Make (Scenarios -> ... -> Import Blueprint), then replace the
{{SLACK_WEBHOOK_URL}}, {{HUBSPOT_TOKEN}} and {{ANTHROPIC_API_KEY}} placeholders
(or better: move them into Make connections / keychain). Secrets never live in this repo.

Scenario 1  "Route scored accounts"
    webhook (from hubspot_sync.py route) -> router
      Tier A + Enterprise        -> Slack AE alert   -> HubSpot owner = AE - Enterprise
      Tier A + Mid-Market/SMB    -> Slack SDR alert  -> HubSpot owner = SDR - Mid-Market
      Tier B                     -> HubSpot owner = Nurture sequence
      Tier C / DQ                -> HubSpot owner = No action
    Every HTTP step has an error route -> #gtm-engine-alerts, then Ignore (skip record, keep running).

Scenario 2  "Handle replies"
    Instantly reply_received webhook -> Claude classifies the reply (JSON) ->
    tag HubSpot contact -> router
      interested -> create HubSpot deal (Qualified to Buy, $60k, assoc. to company) -> company = replied
      always     -> Slack ping with class, summary, next step
"""
import json
import pathlib

SLACK = "{{SLACK_WEBHOOK_URL}}"
HS_AUTH = [{"name": "Authorization", "value": "Bearer {{HUBSPOT_TOKEN}}"}]
COMPANY = "{{ifempty(1.companyName; ifempty(1.company_name; 1.lead_company))}}"
FIRST = "{{ifempty(1.firstName; 1.first_name)}}"
OUT = pathlib.Path(__file__).parent

_ids = iter(range(100, 1000, 10))


def http(name, url, data, method="post", headers=None, *, err_label, err_text, mid):
    """http:ActionSendData v3 with an error route: Slack alert to #gtm-engine-alerts, then Ignore."""
    eid = next(_ids)
    return {
        "id": mid, "module": "http:ActionSendData", "version": 3,
        "mapper": {"url": url, "data": data, "method": method, "headers": headers or [],
                   "bodyType": "raw", "contentType": "application/json", "parseResponse": True},
        "parameters": {"handleErrors": True},
        "metadata": {"designer": {"name": name}},
        "onerror": [
            {"id": eid, "module": "http:ActionSendData", "version": 3,
             "mapper": {"url": SLACK, "method": "post", "headers": [], "bodyType": "raw",
                        "contentType": "application/json",
                        "data": json.dumps({"text": f":rotating_light: *{err_label}* {err_text} Error: {{{{error.message}}}}"})},
             "parameters": {"handleErrors": True},
             "metadata": {"designer": {"name": "Error -> #gtm-engine-alerts"}}},
            {"id": eid + 1, "module": "builtin:Ignore", "version": 1, "mapper": None, "parameters": {}},
        ],
    }


def filt(name, *conds):
    return {"name": name, "conditions": [[{"a": a, "b": b, "o": o} if b is not None else {"a": a, "o": o}
                                          for a, b, o in conds]]}


def scenario(name, flow):
    return {"name": name, "flow": flow,
            "metadata": {"instant": True, "version": 1,
                         "scenario": {"roundtrips": 1, "maxErrors": 3, "autoCommit": True,
                                      "autoCommitTriggerLast": True, "sequential": False,
                                      "confidential": False, "dataloss": False, "dlq": False,
                                      "freshVariables": False}}}


# ---------------------------------------------------------------- scenario 1: routing
def mark_routed(mid, owner):
    return http("HubSpot: mark routed",
                "https://api.hubapi.com/crm/v3/objects/companies/{{1.hubspot_id}}",
                json.dumps({"properties": {"gtm_engine_status": "routed", "gtm_routing_owner": owner}}),
                "patch", HS_AUTH, mid=mid, err_label="GTM Engine error",
                err_text="in step _HubSpot update_ for *{{1.company}}* ({{1.account_key}}). Record skipped.")


def slack_alert(mid, text):
    return http("Slack alert", SLACK, json.dumps({"text": text}), mid=mid, err_label="GTM Engine error",
                err_text="in step _Slack alert_ for *{{1.company}}* ({{1.account_key}}). Record skipped.")


AE_TEXT = (":dart: *Tier A - Enterprise -> AE* | *{{1.company}}* (fit {{1.score}}/100)\n{{1.reasoning_esc}}\n"
           "*Brief*\n{{1.brief_esc}}\n*Lead contact:* {{1.contact_esc}}\n<{{1.hubspot_url}}|Open in HubSpot>")
SDR_TEXT = (":zap: *Tier A - {{1.segment_label}} -> SDR* | *{{1.company}}* (fit {{1.score}}/100)\n{{1.reasoning_esc}}\n"
            "*First line ready:* {{1.first_line_esc}}\n*Contact:* {{1.contact_esc}}\n<{{1.hubspot_url}}|Open in HubSpot>")


def route(first_step, *rest, f):
    first_step["filter"] = f
    return {"flow": [first_step, *rest]}


routing = scenario("GTM Engine - Route scored accounts", [
    {"id": 1, "module": "gateway:CustomWebHook", "version": 1, "mapper": {},
     "parameters": {"hook": "<your webhook id>", "maxResults": 1},
     "metadata": {"designer": {"name": "Scored account in (from AI layer)"}}},
    {"id": 2, "module": "builtin:BasicRouter", "version": 1, "mapper": None, "routes": [
        route(slack_alert(10, AE_TEXT), mark_routed(11, "AE - Enterprise"),
              f=filt("Tier A + Enterprise", ("{{1.tier}}", "A", "text:equal"),
                     ("{{1.segment}}", "enterprise", "text:equal"))),
        route(slack_alert(20, SDR_TEXT), mark_routed(21, "SDR - Mid-Market"),
              f=filt("Tier A + Mid-Market/SMB/Unknown", ("{{1.tier}}", "A", "text:equal"),
                     ("{{1.segment}}", "enterprise", "text:notequal"))),
        route(mark_routed(30, "Nurture sequence"), f=filt("Tier B -> nurture", ("{{1.tier}}", "B", "text:equal"))),
        route(mark_routed(40, "No action (C/DQ)"),
              f=filt("Tier C / DQ -> park", ("{{1.tier}}", "A", "text:notequal"), ("{{1.tier}}", "B", "text:notequal"))),
    ]},
])

# ---------------------------------------------------------------- scenario 2: replies
CLASSIFY_PROMPT = (
    "You classify replies to a B2B cold email from Brava Robotics (humanoid robots for warehouse tote handling). "
    "Return ONLY a JSON object, no code fences:\n"
    '{"class": "interested" | "objection" | "not_now" | "wrong_person" | "unsubscribe" | "out_of_office", '
    '"summary": "<one sentence, max 25 words>", "next_step": "<one concrete action for the rep, max 20 words>"}\n\n'
    f"Prospect: {FIRST} at {COMPANY}\nReply:\n{{{{ifempty(1.reply_text; ifempty(1.reply_text_snippet; 1.text))}}}}"
)
SLACK_PING = (
    '{{if(4.class = "interested"; ":fire: *Positive reply -> deal created*"; ":speech_balloon: *Reply received*")}}'
    f" | *{COMPANY}* ({FIRST})\n*AI class:* `{{{{4.class}}}}`\n*Summary:* {{{{4.summary}}}}\n"
    "*Next step:* {{4.next_step}}\n"
    "<https://app.hubspot.com/contacts/<portal-id>/record/0-2/{{1.hubspot_company_id}}|Open company in HubSpot>"
)
ERR = "GTM Engine reply-handler error"

deal_body = ('{"properties":{"dealname":"' + COMPANY + ' - Brava pilot (inbound reply)","pipeline":"default",'
             '"dealstage":"qualifiedtobuy","amount":"60000"},"associations":[{"to":{"id":"{{1.hubspot_company_id}}"},'
             '"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":5}]}]}')

replies = scenario("GTM Engine - Handle replies", [
    {"id": 1, "module": "gateway:CustomWebHook", "version": 1, "mapper": {},
     "parameters": {"hook": "<your webhook id>", "maxResults": 1},
     "metadata": {"designer": {"name": "Instantly: reply_received"}}},
    # TransformToJSON makes the free-text reply safe to embed in the API body (quotes, newlines).
    {"id": 2, "module": "json:TransformToJSON", "version": 1, "mapper": {"object": CLASSIFY_PROMPT},
     "parameters": {"space": ""}, "metadata": {"designer": {"name": "Build classifier prompt (JSON-safe)"}}},
    http("Claude: classify reply", "https://api.anthropic.com/v1/messages",
         '{"model":"claude-haiku-5-5","max_tokens":1500,"messages":[{"role":"user","content":{{2.json}}}]}',
         headers=[{"name": "x-api-key", "value": "{{ANTHROPIC_API_KEY}}"},
                  {"name": "anthropic-version", "value": "2023-06-01"}],
         mid=3, err_label=ERR, err_text="at _Claude classify_ for {{1.lead_email}}."),
    # The response can start with a non-text block, so pick the first block whose type is "text".
    {"id": 4, "module": "json:ParseJSON", "version": 1,
     "mapper": {"json": '{{first(map(3.data.content; "text"; "type"; "text"))}}'},
     "parameters": {"type": ""}, "metadata": {"designer": {"name": "Parse AI verdict"}}},
    http("HubSpot: tag contact reply class",
         "https://api.hubapi.com/crm/v3/objects/contacts/{{ifempty(1.lead_email; 1.email)}}?idProperty=email",
         '{"properties":{"gtm_reply_class":"{{4.class}}"}}', "patch", HS_AUTH,
         mid=5, err_label=ERR, err_text="at _HubSpot contact update_ for {{1.lead_email}}."),
    {"id": 6, "module": "builtin:BasicRouter", "version": 1, "mapper": None, "routes": [
        route(http("HubSpot: create deal (Qualified to Buy)", "https://api.hubapi.com/crm/v3/objects/deals",
                   deal_body, headers=HS_AUTH, mid=10, err_label=ERR,
                   err_text="at _HubSpot deal create_ for {{1.lead_email}}."),
              http("HubSpot: company -> replied",
                   "https://api.hubapi.com/crm/v3/objects/companies/{{1.hubspot_company_id}}",
                   '{"properties":{"gtm_engine_status":"replied"}}', "patch", HS_AUTH,
                   mid=11, err_label=ERR, err_text="at _HubSpot company update_ for {{1.lead_email}}."),
              f=filt("Interested", ("{{4.class}}", "interested", "text:equal"))),
        route({"id": 20, "module": "json:TransformToJSON", "version": 1, "mapper": {"object": SLACK_PING},
               "parameters": {"space": ""}, "metadata": {"designer": {"name": "Build Slack message (JSON-safe)"}}},
              http("Slack: reply ping", SLACK, '{"text":{{20.json}}}', mid=21, err_label=ERR,
                   err_text="at _Slack ping_ for {{1.lead_email}}."),
              f=filt("Always", ("{{4.class}}", None, "exist"))),
    ]},
])

if __name__ == "__main__":
    for fname, bp in [("route_scored_accounts", routing), ("handle_replies", replies)]:
        path = OUT / f"{fname}.blueprint.json"
        path.write_text(json.dumps(bp, indent=2, ensure_ascii=False))
        print("wrote", path)
