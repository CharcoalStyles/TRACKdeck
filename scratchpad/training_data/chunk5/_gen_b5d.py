import json, random, glob, difflib
from datetime import datetime
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Australia/Canberra")
def iso(s):
    d = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    o = d.strftime("%z"); return d.strftime("%Y-%m-%dT%H:%M:00") + o[:3] + ":" + o[3:]
LM = {"learning_mode": True}
def fl(os_=False, **k):
    d = dict(LM); 
    if os_: d["one_shot"] = True
    d.update(k); return d
neg = []  # (text, reply, flags, notes)
def N(text, reply, os_=False, notes="", **k): neg.append((text, reply, fl(os_, **k), notes))

# capability limits
N("turn the heating off for me, I'm heading out the door", "I can't control your heating — I'm not connected to any smart-home gear. I can set a reminder to turn it off if that would help.", notes="Capability-limit: no heating control; positive control B5D is the 'set a reminder to turn the heating off' ask.")
N("can you get the oven up to 200 degrees, I'm about to start the roast", "I can't operate the oven, sorry — nothing on my end connects to your appliances.", notes="Capability-limit: appliance control; paired with a set_timer positive control.")
N("order me a large pepperoni from Dominos, the usual address", "I can't place food orders, so you'll need to order that through their app or phone line.", os_=True, notes="Capability-limit one_shot: ordering food; reply declines and stops.")
N("jump on WhatsApp and ask Marcus if he's still keen for Saturday dinner", "I can't send WhatsApp messages or any other texts for you, so that one's up to you.", notes="Capability-limit: messaging; paired with add_calendar_event positive control.")
N("print out my shopping list so I can stick it on the fridge", "I can't print anything from here — no printer connection on my end.", notes="Capability-limit: printing.")
N("I've got a receipt in front of me, can you read the total off it and log it", "I can't read photos or receipts — I've got no way to see images. If you tell me the total I can save it as a note.", os_=True, notes="Capability-limit one_shot: OCR; offers a real alternative as a statement, no question.")
N("how do I get to the Fyshwick markets from Belconnen and how's the traffic looking", "I can't give directions or live traffic, since I've got no maps access. Your phone's maps app will have the route and the current conditions.", notes="Capability-limit: maps/traffic.")
N("email the notes from yesterday's meeting over to Hannah please", "I can't send emails for you — you'll need to send those notes to Hannah yourself.", os_=True, notes="Capability-limit one_shot: outbound email even though notes exist; no question at end.")
N("set the alarm on my phone for 5:30 with that really loud ringtone", "I can't reach your phone's alarm app. I can set a reminder for 5:30 that sends a notification, but it won't replace a proper alarm.", notes="Capability-limit: device alarm feature; mentions the reminder alternative honestly.")
N("move forty bucks from my savings to Jess for the concert tickets", "I can't make transfers or access any of your banking, so that has to be done in your banking app.", notes="Capability-limit: banking.")

# settings-only
N("can you send the daily recap email at 8pm rather than quarter to nine", "The daily recap time is changed on the Settings page, not from chat. You can set it to 8pm there.", notes="Settings-only: digest time.")
N("switch the daily summary email over so it goes to my work address from now on", "The address the daily summary goes to is changed on the Settings page, so you'll need to update it there.", notes="Settings-only: digest email.")
N("I'm up at 6:15 these days now, change my wake time to match", "Wake time is changed on the Settings page, not by me from chat, so you'll need to update it there.", os_=True, notes="Settings-only one_shot: wake time; no question.")
N("those check-in prompts keep turning up way too late in the evening, can you cut them off at 8pm", "The latest time check-ins can arrive is a Settings page option, so you can change it to 8pm there.", notes="Settings-only: latest check-in time.")
N("make the calendar sync check for changes more often, like every ten minutes", "How often the calendar syncs is set on the Settings page, so you can bring it down to ten minutes there. I can't change it from chat.", notes="Settings-only: calendar sync interval.")
N("get the little handheld to check in with the server every two minutes instead of every five", "That check-in interval is changed on the Settings page. I can't adjust it from chat.", os_=True, notes="Settings-only one_shot: device poll interval.")
N("I've set up a new notifications server at notify.myhome.example, point the push alerts over to it", "The notification server is changed on the Settings page, so you'll need to enter the new address there.", notes="Settings-only: notification server.")
N("can you remember conversations from further back, stretch it out to 90 days", "How far back I recall past conversations is a Settings page option, so you can change it to 90 days there.", notes="Settings-only: recall window.")
N("go back to the local model now, the cloud one's been giving me weird answers", "Which model I run on is switched on the Settings page, not from chat. You can pick the local one there.", os_=True, notes="Settings-only one_shot: model/provider.")

# moved
N("we've relocated to Hobart as of last week, I live in Tasmania now", "Congratulations on the move to Hobart. The home location is changed on the Settings page, so update it there and the weather will follow.", os_=True, notes="Ordinary-chat move one_shot: set_home_location is onboarding-only; point to Settings.")
N("I'm in Darwin for work for a fortnight so can you switch my time zone over until I'm back", "Safe travels to Darwin. The time zone is changed on the Settings page, so you'll need to switch it there, and back again when you return.", notes="Ordinary-chat travel: timezone is settings-only.")
N("we finally bought a place out in Bungendore, so that's where home is now", "Congratulations on the new place. To use Bungendore for weather and the like, change the home location on the Settings page.", os_=True, notes="Ordinary-chat move one_shot: no question at end.")

# look-alike
N("can you ping me every Friday afternoon to water the ferns", "Reminders only work as one-off ones, so I can't repeat a Friday one. I can add a weekly calendar event for Friday afternoons instead. What time would suit?", notes="Look-alike: recurring reminder; offer recurring calendar event as a question (non one_shot).")
N("how would I go about saving a thought with you so I can find it later", "Just tell me what to note, something like 'save a note that the car needs a service', and give it a title if you like. Later you can ask me to find it by topic.", notes="Look-alike: how-to question about notes, no call.")
N("my calendar this week is an absolute nightmare, everything is back to back", "That sounds exhausting. If you'd like a rundown of what's on, just ask and I'll pull it up.", notes="Look-alike: venting about a busy calendar, no lookup requested.")
N("quick one, which city is Slovenia's capital", "It's Ljubljana.", os_=True, notes="Look-alike one_shot: general knowledge.")
N("what would you do if it bucketed down on Saturday and the picnic was off", "I'd move it indoors, maybe a long lunch at a cafe or a games afternoon at home, and keep the picnic food for a dry day.", notes="Look-alike: hypothetical, no weather lookup requested.")
N("ugh it's absolutely freezing this morning", "Brr, that's a cold start. A warm drink and an extra layer should help.", notes="Look-alike: weather commentary with no request; paired with a weather positive control.")
N("all sorted then, I'll leave you to it", "Anytime, talk soon.", notes="Look-alike: sign-off.")
N("that meeting with the landlord yesterday was a disaster, he just wouldn't budge on the rent", "That sounds frustrating, sorry it went that way. If you want to think through next steps, I'm happy to talk it over.", notes="Look-alike: discussing a past event, no lookup or save requested.")
N("can you pop it in the calendar for me", "Happy to, but what's the event, and what day and time should I put it on?", notes="Look-alike: missing every required detail, non one_shot clarifying question.")
N("shift my appointment to later in the day", "Which appointment do you mean, and what time would you like it moved to?", notes="Look-alike: ambiguous update, needs info that can't be defaulted; non one_shot.")
N("tell me a joke about penguins", "Why don't penguins fly? They're not tall enough to be pilots.", os_=True, notes="Look-alike one_shot: joke.")

# modes
N("random thing, what's a good banana bread recipe", "That's outside what I can help with in your profile chat. I'm happy to help with it in a regular chat, just not from in here.", mode="profile_chat", notes="Mode-scoped negative: off-topic in profile_chat.")
N("sorry, long day. how's your day been?", "All good here, thanks. Whenever you're ready, tell me what a usual weekday morning looks like for you.", mode="onboarding", notes="Mode-scoped: small talk during onboarding, gently steer back; non one_shot so a question-ish steer is fine.")
N("I just can't face doing any of this list today", "That happens. Pick the one thing that matters most and start there, and the rest can wait.", mode="day_planning", notes="Mode-scoped: venting during day_planning, no task to add.")
N("who won the Tour de France last year", "That's outside the bike-commute project, so I'll leave that one for a regular chat.", mode="project_chat", project="bike-commute", group="bike-commute", notes="Mode-scoped: general-knowledge question in project_chat.")
N("can you email my profile summary to my sister", "I can't send emails, so you'd need to pass that on to her yourself.", os_=True, mode="profile_chat", notes="Mode-scoped capability limit one_shot in profile_chat.")

assert len(neg) == 38, len(neg)

pos = []
def P(anchor, text, flags, turns, intents, notes, **extra):
    r = {"anchor": iso(anchor), "flags": flags, "text": text, "turns": turns, "notes": notes}
    if intents: r["date_intents"] = intents
    r.update(extra); pos.append(r)
tc = lambda *calls: {"tool_calls": [{"name": n, "args": a} for n, a in calls], "content": ""}
P("2027-02-09 17:40", "set me a reminder to turn the heating off at ten tonight", fl(),
  [tc(("set_reminder", {"message": "Turn the heating off", "when": "2027-02-09 22:00:00"})),
   {"tool_results": ["Got it — I'll remind you to 'Turn the heating off' at Tuesday, 09 February 2027 10:00 PM."]},
   {"content": "Done, I'll remind you at 10pm tonight to turn the heating off."}],
  [{"phrase": "ten tonight", "arg": "set_reminder.when"}], "Positive control: reminder to do it is a tool call, unlike turning the heating off itself.", category="reminders")
P("2026-06-18 08:15", "can you start a weekly timesheet submission event in the calendar, next Monday at 9am and then every Monday after that", fl(),
  [tc(("add_calendar_event", {"title": "Submit timesheet", "start": "2026-06-22 09:00:00", "recurrence": "FREQ=WEEKLY;BYDAY=MO"})),
   {"tool_results": ["Event added successfully. UID: 4d8b2f61-3c7a-4e19-b5a0-9f2c1d7e6a38"]},
   {"content": "Added. Submit timesheet repeats every Monday at 9am, starting Monday 22 June."}],
  [{"phrase": "next Monday at 9am", "arg": "add_calendar_event.start"}], "Positive control: recurring calendar event, the alternative offered to recurring-reminder requests.", category="calendar")
P("2028-01-02 19:30", "set a timer for 12 minutes, the oven's preheating and I don't want to forget the tray", fl(),
  [tc(("set_timer", {"message": "Put the tray in the oven", "when": "2028-01-02 19:42:00"})),
   {"tool_results": ["Got it — I'll remind you to 'Put the tray in the oven' at Sunday, 02 January 2028 07:42 PM."]},
   {"content": "Timer set for 12 minutes, I'll ping you at 7:42pm to put the tray in."}],
  [{"phrase": "12 minutes", "arg": "set_timer.when"}], "Positive control: timer is a tool even though operating the oven is not.", category="reminders")
P("2026-12-30 11:05", "what's it actually like out there at the moment, thinking of hanging the washing", fl(True),
  [tc(("get_current_weather", {})),
   {"tool_results": ["Weather for Canberra: 31.2°C, 8% cloud cover, 0.0mm precipitation."]},
   {"content": "It's 31.2°C with hardly any cloud and no rain, so the washing will dry quickly."}],
  [], "Positive control: actual weather question versus weather commentary.", category="weather")
P("2027-08-12 20:10", "can you add a dinner with Marcus on Saturday at 7pm, evenings are filling up", fl(),
  [tc(("add_calendar_event", {"title": "Dinner with Marcus", "start": "2027-08-14 19:00:00"})),
   {"tool_results": ["Event added successfully. UID: 8e1a5c37-2b4d-4f60-a9c3-7d5e0b1f2a94"]},
   {"content": "Added dinner with Marcus on Saturday 14 August at 7pm."}],
  [{"phrase": "Saturday at 7pm", "arg": "add_calendar_event.start"}], "Positive control: calendar entry versus messaging a person.", category="calendar")
P("2026-09-26 09:30", "look up the phone number for the pizza place in Kaleen, I'll ring them myself", fl(True),
  [tc(("search_web", {"query": "pizza restaurant Kaleen phone number"})),
   {"tool_results": ["{\"query\":\"pizza restaurant Kaleen phone number\",\"total_results\":4,\"results\":[{\"title\":\"Kaleen Pizza Kitchen - Contact\",\"url\":\"https://pizza.example/kaleen\",\"snippet\":\"Call (02) 6555 0142. Open 4pm to 9pm daily.\"}]}"]},
   {"content": "The top result is Kaleen Pizza Kitchen, phone (02) 6555 0142, open 4pm to 9pm daily."}],
  [], "Positive control: looking up a number is a search; placing the order is not possible.", category="web")
P("2027-11-19 22:45", "quick save to the project, the tile guy quoted 38 dollars a square metre for the splashback", fl(mode="project_chat", project="kitchen-reno"),
  [tc(("save_note", {"title": "Splashback tile quote", "content": "Tile supplier quoted $38 per square metre for the splashback.", "project": "kitchen-reno"})),
   {"tool_results": ["Note saved: 'Splashback tile quote' (id: 7c2e4b91)."]},
   {"content": "Saved the splashback quote to the kitchen-reno project."}],
  [], "Positive control in project_chat: save_note with project, versus off-topic project questions.", category="notes", group="kitchen-reno")
P("2028-03-07 07:20", "morning, run me through today's calendar and whether the clothes line's a go", fl(),
  [tc(("get_todays_events", {}), ("get_current_weather", {})),
   {"tool_results": ["[{\"alarms\": [], \"generated\": false, \"uid\": \"3b9d7e21-6c4a-4f18-8d05-2a1e9c7b4f63\", \"start\": \"20280306T230000Z\", \"end\": \"20280307T000000Z\", \"description\": \"\", \"summary\": \"Quarterly planning\"}, {\"alarms\": [], \"generated\": false, \"uid\": \"5f2a8c14-9e7b-4d30-a6c1-8b3d0e5f7a92\", \"start\": \"20280307T043000Z\", \"end\": \"20280307T050000Z\", \"description\": \"\", \"summary\": \"Dentist check-up\"}]",
                       "Weather for Canberra: 19.6°C, 40% cloud cover, 0.0mm precipitation."]},
   {"content": "Two things on today, quarterly planning from 10 to 11am and a dentist check-up at 3:30pm. It's 19.6°C and dry with some cloud, so the clothes line should be fine."}],
  [], "Positive control: parallel events + weather lookup versus venting about a busy calendar.", category="calendar")
assert len(pos) == 8

# anchors for negatives
rng = random.Random(5405)
used = {p["anchor"] for p in pos}
def rand_anchor():
    while True:
        y = rng.choice([2026, 2027, 2028]); mo = rng.randint(1, 12)
        if (y, mo) < (2026, 3): continue
        d = rng.randint(1, 28); h = rng.randint(6, 23); mi = rng.choice([0, 5, 10, 15, 20, 30, 40, 45, 50, 55])
        if h == 23 and mi > 40: continue
        a = iso(f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}")
        if a not in used: used.add(a); return a
recs = []
for text, reply, flags, notes in neg:
    r = {"source": "synthetic", "category": "no_tool", "anchor": rand_anchor(), "flags": flags, "text": text,
         "turns": [{"content": reply}], "notes": notes}
    if "project" in flags: r["group"] = flags["project"]
    recs.append(r)
for p in pos:
    cat = p.pop("category"); g = p.pop("group", None)
    r = {"source": "synthetic", "category": cat}; r.update(p)
    if g: r["group"] = g
    recs.append(r)
rng.shuffle(recs)
out = []
for i, r in enumerate(recs, 1):
    o = {"id": f"B5D-{i:04d}"}; o.update(r)
    # key order tidy
    out.append(o)
with open("/home/charcoal/docker/trackdeck/scratchpad/training_data/chunk5/B5D.jsonl", "w") as f:
    for o in out: f.write(json.dumps(o, ensure_ascii=False) + "\n")

# similarity audit
others = []
for fn in glob.glob("/home/charcoal/docker/trackdeck/scratchpad/training_data/chunk*/B*.jsonl"):
    if fn.endswith("B5D.jsonl"): continue
    for l in open(fn): others.append(json.loads(l)["text"].lower())
ev = [x["text"].lower() if isinstance(x, dict) else x.lower() for x in json.load(open("/home/charcoal/docker/trackdeck/scratchpad/eval_prompts.json"))]
sm = lambda a, b: difflib.SequenceMatcher(None, a, b).ratio()
texts = [o["text"].lower() for o in out]
for i, t in enumerate(texts):
    for j in range(i):
        if sm(t, texts[j]) > 0.5: print("SELF-SIM", out[i]["id"], out[j]["id"], round(sm(t, texts[j]), 2))
    m = max(sm(t, e) for e in ev + others)
    if m > 0.55: print("EXT-SIM", out[i]["id"], round(m, 2), t)
print("written", len(out))
