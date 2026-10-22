import json
from datetime import datetime
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Australia/Canberra")
recs = []

def anchor(s, wd):
    dt = datetime.fromisoformat(s).replace(tzinfo=TZ)
    assert dt.strftime("%A") == wd, (s, dt.strftime("%A"))
    assert not (dt.hour == 2), s
    return dt.isoformat()

def res(query, items):
    return json.dumps({"query": query, "total_results": len(items),
                       "results": [{"title": t, "url": u, "snippet": s} for t, u, s in items]})

def rec(kind, anc, wd, text, calls, final, notes, one_shot=False):
    # calls: list of (toolname, args, result)
    turns = []
    for name, args, result in calls:
        turns.append({"tool_calls": [{"name": name, "args": args}], "content": ""})
        turns.append({"tool_results": [result]})
    turns.append({"content": final})
    flags = {"learning_mode": True}
    if one_shot: flags["one_shot"] = True
    first = calls[0][0]
    cat = "general" if first == "fetch_webpage" else "web"
    recs.append({"id": f"B7D-{len(recs)+1:04d}", "source": "synthetic", "category": cat,
                 "anchor": anchor(anc, wd), "flags": flags, "text": text, "turns": turns, "notes": notes})

def web(q, items, **kw):
    a = {"query": q}; a.update(kw)
    return ("search_web", a, res(q, items))
def news(q, items, **kw):
    a = {"query": q}; a.update(kw)
    return ("search_news", a, res(q, items))
def fetch(u, body):
    return ("fetch_webpage", {"url": u}, body)

# ---- search_web only ----
rec("w", "2026-10-17T09:05:00", "Saturday",
 "what time does the Belconnen Fresh Food Market open on Sundays, thinking of going tomorrow",
 [web("Belconnen Fresh Food Market Sunday opening hours", [
  ("Belconnen Fresh Food Market - Visit", "https://belconnenmarkets.example/visit", "Open Wednesday to Sunday. Sunday trading hours are 9am-3pm, with free parking on site."),
  ("Belconnen Markets trading hours", "https://canberraguide.example/belconnen-markets", "Wednesday to Friday 8am-5pm, Saturday 8am-4pm, Sunday 9am-3pm."),
  ("Belconnen Fresh Food Market reviews", "https://reviewhub.example/belconnen-fresh-food-market", "Locals rate the Sunday stalls highly for fresh bread and flowers; arrive early for parking.")])],
 "The market's open from 9am to 3pm on Sundays, so tomorrow works. Parking on site is free.",
 "Opening hours for a named business -> search_web; single call then answer.")

rec("w", "2026-11-03T19:40:00", "Tuesday",
 "how much is the new Kindle Scribe in Australia now",
 [web("Kindle Scribe price Australia", [
  ("Kindle Scribe (16 GB) - Amazon Australia", "https://shop.example.au/kindle-scribe-16gb", "Kindle Scribe 16 GB with Basic Pen: A$599. Free delivery on orders over A$59."),
  ("Kindle Scribe 32 GB Premium Pen bundle", "https://shop.example.au/kindle-scribe-32gb-premium", "Kindle Scribe 32 GB with Premium Pen: A$679."),
  ("Kindle Scribe review: is it worth it?", "https://techreview.example/kindle-scribe-review", "A large 10.2-inch display and a pen for notes, but note-taking features remain basic compared with dedicated tablets.")])],
 "The 16 GB Kindle Scribe with the basic pen is listed at $599, and the 32 GB with the premium pen is $679.",
 "Current price -> search_web.")

rec("w", "2027-05-09T08:15:00", "Sunday",
 "did the Brumbies win last night",
 [web("Brumbies result Saturday 8 May 2027", [
  ("Brumbies hold off Reds in Canberra thriller", "https://rugbynews.example/brumbies-reds-8-may", "The Brumbies beat the Reds 31-24 at home on Saturday night, scoring four tries to three."),
  ("Super Rugby Pacific round results", "https://rugbynews.example/round-results", "Saturday: Brumbies 31 Reds 24, Blues 28 Chiefs 20."),
  ("Brumbies ladder position after round win", "https://rugbynews.example/ladder", "The win lifts the Brumbies into the top four with two rounds to go.")])],
 "Yes, the Brumbies beat the Reds 31-24 at home last night. The win moves them into the top four.",
 "Sports result; one_shot reply is a plain statement.", one_shot=True)

rec("w", "2027-06-12T16:30:00", "Saturday",
 "I want a proper Anzac biscuit recipe, the chewy kind not the hard ones",
 [web("chewy Anzac biscuits recipe", [
  ("Chewy Anzac Biscuits", "https://bakerbakes.example/chewy-anzac-biscuits", "Mix 1 cup rolled oats, 1 cup plain flour, 1 cup desiccated coconut and 3/4 cup brown sugar. Melt 125 g butter with 2 tbsp golden syrup, stir in 1 tsp bicarb soda dissolved in 2 tbsp boiling water, and combine. Bake at 160C for 12-14 minutes for a chewy centre."),
  ("Classic Anzac biscuits", "https://oldschool.example/anzac-biscuits", "A crisp traditional version baked about 20 minutes at 150C."),
  ("Tips for chewy Anzacs", "https://bakerbakes.example/anzac-tips", "Use more golden syrup and less baking time, and take them out while the centres still look slightly soft.")])],
 "One recipe uses 1 cup each of rolled oats, plain flour and coconut with 3/4 cup brown sugar, plus 125 g melted butter with 2 tablespoons golden syrup and the bicarb in boiling water. Bake at 160C for 12 to 14 minutes. Pulling them out while the centres still look soft helps keep them chewy.",
 "Recipe needing a source; answer only from snippets.")

rec("w", "2028-01-02T07:50:00", "Sunday",
 "how long's the drive from Canberra to Jindabyne, we're heading down for the day",
 [web("drive time Canberra to Jindabyne", [
  ("Canberra to Jindabyne drive", "https://roadtrips.example/canberra-jindabyne", "About 210 km via the Monaro Highway and Kosciuszko Road, taking roughly 2 hours 30 minutes without stops."),
  ("Jindabyne travel guide", "https://snowyvisit.example/getting-here", "Jindabyne is around 2.5 to 3 hours from Canberra depending on traffic through Cooma.")])],
 "It's about 210 km and roughly 2 hours 30 minutes without stops. Allow closer to 3 hours if there's traffic through Cooma.",
 "Travel time needing current info.", one_shot=True)

rec("w", "2026-10-10T14:30:00", "Saturday",
 "what are the Floriade opening times this year",
 [web("Floriade 2026 opening times", [
  ("Floriade 2026 - Plan your visit", "https://floriade.example/plan-your-visit", "Floriade is open daily from 9am to 5pm, and Floriade Nightfest runs Friday and Saturday evenings until 9pm. Entry is free."),
  ("Floriade 2026 dates and events", "https://canberraevents.example/floriade-2026", "The festival runs through mid-October in Commonwealth Park, with food stalls and live music on weekends.")])],
 "Floriade is open daily from 9am to 5pm, with Nightfest running until 9pm on Friday and Saturday evenings. Entry is free.",
 "Event info -> search_web.")

rec("w", "2027-08-23T12:20:00", "Monday",
 "what time does the Belconnen library shut on Saturdays",
 [web("Belconnen Library opening hours Saturday", [
  ("Belconnen Library - Libraries ACT", "https://libraries.example/belconnen", "Monday to Thursday 10am-8pm, Friday 10am-6pm, Saturday 10am-4pm, Sunday 1pm-5pm."),
  ("Libraries ACT branches and hours", "https://libraries.example/branches", "Branch hours vary; check each library page for public holiday closures.")])],
 "The Belconnen library closes at 4pm on Saturdays, opening at 10am.",
 "Local business hours.")

rec("w", "2028-04-11T21:10:00", "Tuesday",
 "do I need a licence to fly a drone for fun in the ACT",
 [web("drone rules recreational Australia licence CASA", [
  ("Flying drones for fun - CASA", "https://casa.example/drones/recreational", "Recreational flyers under 2 kg generally don't need a licence or registration but must keep the drone below 120 metres, within visual line of sight, and away from people and airports."),
  ("Drone rules in Canberra", "https://canberradrones.example/rules", "Much of Canberra sits inside controlled airspace near the airport, so check airspace maps before flying and avoid restricted areas around the city."),
  ("Do I need to register my drone?", "https://casa.example/drones/register", "Drones over 250 g used commercially must be registered; recreational use has lighter requirements.")])],
 "For recreational flying under 2 kg you generally don't need a licence, but the drone has to stay under 120 metres, within sight, and away from people and airports. Canberra has a lot of controlled airspace near the airport, so it's worth checking an airspace map first.",
 "Rules needing current source.")

rec("w", "2027-02-19T22:35:00", "Friday",
 "what's a decent ergonomic keyboard under two hundred dollars, just read me what the reviews say",
 [web("best ergonomic keyboard under $200 review", [
  ("Best ergonomic keyboards 2027", "https://keyboardlab.example/best-ergonomic", "Top pick under $200 is the Kinesis-style split Logi Ergo K860 at about $150, praised for its curved layout and wrist rest."),
  ("Microsoft Sculpt Ergonomic review", "https://techreview.example/sculpt-ergonomic", "A comfortable wireless option around $130, though some users find the split spacebar awkward."),
  ("Split keyboards for beginners", "https://typingguide.example/split-beginners", "The Logitech Ergo K860 and Microsoft Sculpt are the most commonly recommended entry points.")])],
 "Reviews most often point to the Logitech Ergo K860 at about $150, praised for its curved layout and wrist rest. The Microsoft Sculpt Ergonomic at around $130 is also recommended, though some find its split spacebar awkward.",
 "Reviews -> search_web; one_shot, no question.", one_shot=True)

rec("w", "2027-09-14T10:25:00", "Tuesday",
 "how much does it cost to renew a passport at the moment",
 [web("Australian passport renewal fee", [
  ("Passport fees - Australian Passport Office", "https://passports.example/fees", "Adult passport (10 years): A$412. Child under 16 (5 years): A$208. Priority processing adds A$225."),
  ("Renew your passport", "https://passports.example/renew", "Standard processing takes up to 6 weeks; priority processing takes about 2 business days."),
  ("Passport price guide", "https://travelhelp.example/passport-costs", "Adult 10-year passports cost A$412 for standard processing.")])],
 "An adult 10-year passport is listed at $412, and priority processing adds $225. Standard processing takes up to 6 weeks.",
 "Current price/fee.")

rec("w", "2027-12-20T17:05:00", "Monday",
 "what are the Canberra Centre trading hours over Christmas",
 [web("Canberra Centre Christmas trading hours", [
  ("Christmas trading hours - Canberra Centre", "https://canberracentre.example/christmas-hours", "Christmas Eve 8am-6pm, Christmas Day closed, Boxing Day 9am-5pm, 27 to 31 December 9am-6pm."),
  ("Canberra Christmas shopping hours", "https://canberratimes.example/christmas-shopping-hours", "Most major retailers will trade extended hours up to Christmas Eve and reopen on Boxing Day.")])],
 "Canberra Centre is open 8am to 6pm on Christmas Eve, closed on Christmas Day, then 9am to 5pm on Boxing Day. From 27 to 31 December it trades 9am to 6pm.",
 "Seasonal trading hours; answer limited to result.")

rec("w", "2028-07-29T11:45:00", "Saturday",
 "how long does the Steam Deck OLED battery actually last",
 [web("Steam Deck OLED battery life", [
  ("Steam Deck OLED battery life tested", "https://handheldreview.example/steam-deck-oled-battery", "In testing, the OLED model lasted 3 to 12 hours depending on the game, with demanding titles at the low end and light 2D games at the top."),
  ("Steam Deck OLED vs LCD battery", "https://handheldreview.example/oled-vs-lcd", "The 50Wh battery in the OLED model gives about 30 to 50 percent more life than the LCD version."),
  ("Specs: Steam Deck OLED", "https://store.example/steam-deck-oled", "50Wh battery, 90Hz HDR display.")])],
 "Testing found anywhere from 3 to 12 hours depending on the game, with demanding titles at the low end. The OLED's 50Wh battery gives roughly 30 to 50 percent more than the LCD version.",
 "Product spec test results.")

rec("w", "2028-10-15T19:15:00", "Sunday",
 "how do I renew my car rego in the ACT online, and what does it cost",
 [web("renew vehicle registration ACT online cost", [
  ("Renew your registration - Access Canberra", "https://accesscanberra.example/renew-rego", "Renew online with your plate number and the renewal notice details. Fees depend on vehicle type and weight and you can pay by card."),
  ("Registration fees 2028-29", "https://accesscanberra.example/rego-fees", "A standard passenger vehicle 12 month registration is from A$1,070, which includes the traffic and compulsory third-party insurance components."),
  ("Do I need an inspection?", "https://accesscanberra.example/inspections", "Inspections are required only for vehicles over a set age or when transferring ownership.")])],
 "You can renew online through Access Canberra using your plate number and the details on your renewal notice, paying by card. A standard passenger vehicle's 12 month registration is listed from $1,070, though the exact fee depends on the vehicle type and weight.",
 "Online renewal + cost; one_shot with no question.", one_shot=True)

rec("w", "2026-10-20T13:00:00", "Tuesday",
 "what's the newest Python version out right now",
 [web("latest Python release", [
  ("Python 3.15.0 Release", "https://python.example/downloads/release/python-3150", "Python 3.15.0 was released on 1 October 2026."),
  ("What's new in Python 3.15", "https://docs.python.example/3.15/whatsnew", "Python 3.15 adds improvements to the interpreter's startup time and new standard library features."),
  ("Python release schedule", "https://python.example/dev/peps/release-schedule", "3.15 final is dated for October 2026, with 3.14 moving into bugfix-only support.")])],
 "The newest release is Python 3.15.0, which came out on 1 October 2026.",
 "Recent product release.")

rec("w", "2027-03-27T06:10:00", "Saturday",
 "what are the visiting hours at the Canberra hospital, my aunt's in there",
 [web("Canberra Hospital visiting hours", [
  ("Visiting hours - Canberra Health Services", "https://health.example/canberra-hospital/visiting", "General wards: 10am-12pm, 2pm-4pm and 6pm-8pm daily. Intensive care and maternity units have separate hours, and visitors may be restricted during outbreaks."),
  ("Canberra Hospital - patient information", "https://health.example/canberra-hospital/patients", "Contact the ward directly for unit specific visiting arrangements.")])],
 "General wards are open for visitors 10am to 12pm, 2pm to 4pm and 6pm to 8pm daily. Intensive care and maternity have their own hours, so it's worth contacting her ward directly.",
 "Local hours with caveat from result.")

rec("w", "2028-12-03T20:30:00", "Sunday",
 "when's the first train from Canberra to Sydney on a Sunday",
 [web("NSW TrainLink Canberra to Sydney Sunday first train", [
  ("Canberra to Sydney timetable - NSW TrainLink", "https://trainlink.example/canberra-sydney", "Sunday services depart Canberra at 6:37am, 12:22pm and 5:14pm. Journey time is about 4 hours 10 minutes."),
  ("Canberra Railway Station", "https://trainlink.example/stations/canberra", "Tickets can be bought online or at the station."),
  ("Plan your trip", "https://trainlink.example/plan", "Timetables may change; check closer to your travel date.")])],
 "The first Sunday train leaves Canberra at 6:37am, then there are others at 12:22pm and 5:14pm. The trip takes about 4 hours 10 minutes, though timetables can change so check closer to the date.",
 "Timetable info.")

# ---- search -> single fetch (4) ----
rec("sf", "2026-12-09T18:20:00", "Wednesday",
 "can you find me the full menu and prices for that new ramen place in Braddon",
 [web("new ramen restaurant Braddon Canberra menu", [
   ("Kiri Ramen Braddon - Menu", "https://kiriramen.example/menu", "See the full menu and prices for Kiri Ramen on Lonsdale Street."),
   ("Kiri Ramen opens in Braddon", "https://canberraeats.example/kiri-ramen-opens", "A new ramen bar has opened on Lonsdale Street serving tonkotsu and miso broths.")]),
  fetch("https://kiriramen.example/menu",
   "Kiri Ramen - Menu\n\nRamen\nTonkotsu Ramen - $19\nMiso Ramen - $18\nSpicy Chilli Ramen - $20\nVegetable Shoyu Ramen (vegetarian) - $17\n\nSides\nGyoza (5 pieces) - $9\nKaraage Chicken - $12\nEdamame - $6\n\nExtras\nSoft boiled egg - $2.50\nExtra noodles - $3\n\nOpen Tuesday to Sunday, 11:30am-9pm.")],
 "Kiri Ramen has tonkotsu at $19, miso at $18, spicy chilli at $20 and a vegetarian shoyu at $17. Sides include gyoza at $9, karaage chicken at $12 and edamame at $6. They're open Tuesday to Sunday, 11:30am to 9pm.",
 "Search snippet only points at the menu page, so one fetch_webpage then answer.")

rec("sf", "2027-02-24T15:50:00", "Wednesday",
 "I want the day by day schedule for the Balloon Spectacular, just give me the main bits",
 [web("Canberra Balloon Spectacular 2027 schedule", [
   ("Canberra Balloon Spectacular 2027 - Program", "https://balloonspectacular.example/program", "View the daily program including launch times, night glow and evening events."),
   ("Balloon Spectacular returns this March", "https://canberratimes.example/balloon-spectacular-2027", "Dozens of hot air balloons will rise over Lake Burley Griffin each morning of the festival.")]),
  fetch("https://balloonspectacular.example/program",
   "Canberra Balloon Spectacular 2027 - Daily Program\n\nDaily mass ascent: 6:30am at Commonwealth Park (weather permitting)\nFood and market stalls: 7am-1pm\nFriday: Night Glow 7:30pm\nSaturday: Family fun morning 8am-11am and Night Glow 7:30pm\nSunday: Final ascent 6:30am, closing ceremony 9am\n\nAll launches are subject to weather conditions. Entry is free.")],
 "There's a mass ascent each morning at 6:30am in Commonwealth Park, weather permitting, with stalls from 7am to 1pm. A Night Glow runs at 7:30pm on Friday and Saturday, with a family morning on Saturday from 8am to 11am. Sunday finishes with a final ascent at 6:30am and a closing ceremony at 9am, and all launches depend on the weather.",
 "Single fetch for specifics; one_shot ends on statement.", one_shot=True)

rec("sf", "2028-02-29T09:30:00", "Tuesday",
 "what do I actually need to bring to join the library, the real requirements",
 [web("Libraries ACT join library membership requirements", [
   ("Join the library - Libraries ACT", "https://libraries.example/join", "Find out how to become a member, including what ID you need to bring."),
   ("Library membership FAQ", "https://libraries.example/faq", "Membership is free for ACT residents.")]),
  fetch("https://libraries.example/join",
   "Join the library\n\nMembership is free for all ACT residents.\n\nWhat to bring:\n- One form of photo ID (for example a driver licence or passport)\n- Proof of your current ACT address if it is not shown on your ID (a utility bill or rates notice from the last 3 months)\n\nChildren under 16 can join with a parent or guardian, who must provide their own ID.\n\nYour card is issued on the spot and you can borrow up to 30 items.")],
 "Membership is free for ACT residents. Bring one form of photo ID, plus proof of your ACT address like a recent bill if it's not on the ID. Your card is issued on the spot and lets you borrow up to 30 items.",
 "Search then one fetch.")

rec("sf", "2027-07-04T16:00:00", "Sunday",
 "find me a lamb shank recipe with the actual method, I'd like to do it tonight",
 [web("slow cooked lamb shanks recipe", [
   ("Slow Braised Lamb Shanks", "https://tablefare.example/braised-lamb-shanks", "Fall-off-the-bone lamb shanks in a red wine and tomato sauce. Full method on the page."),
   ("Lamb shank recipes", "https://tablefare.example/lamb-shanks", "A collection of oven, slow cooker and pressure cooker lamb shank recipes.")]),
  fetch("https://tablefare.example/braised-lamb-shanks",
   "Slow Braised Lamb Shanks - serves 4\n\nIngredients: 4 lamb shanks, 2 tbsp olive oil, 1 onion, 2 carrots, 3 garlic cloves, 1 cup red wine, 400 g tin crushed tomatoes, 1 cup beef stock, 2 sprigs rosemary.\n\nMethod:\n1. Preheat oven to 160C. Brown shanks in oil in a heavy casserole, then set aside.\n2. Cook chopped onion, carrot and garlic for 5 minutes. Add wine and simmer 3 minutes.\n3. Add tomatoes, stock and rosemary, return the shanks, cover and braise in the oven for 3 hours, turning once.\n4. Rest for 10 minutes and serve with mash.")],
 "It's a braise for four: brown the shanks, soften onion, carrot and garlic, then add wine, crushed tomatoes, stock and rosemary. Cover and cook in a 160C oven for 3 hours, turning once, then rest for 10 minutes. That's about three hours before dinner, so you'd want to start soon.",
 "Recipe needing a source; one fetch then answer.")

# ---- direct fetch (6) ----
rec("f", "2026-11-22T10:40:00", "Sunday",
 "have a read of this and give me the main points https://citynews.example/2026/11/new-bike-path-network",
 [fetch("https://citynews.example/2026/11/new-bike-path-network",
   "New bike path network approved for inner north\n\nThe ACT Government has approved a 14 km network of separated bike paths linking Civic, Braddon and Dickson. Construction is due to begin in March 2027 and finish by the end of 2028, with a budget of $38 million. Some on-street parking along Northbourne Avenue will be removed. A community consultation session is planned for early December.")],
 "The government has approved a 14 km separated bike path network linking Civic, Braddon and Dickson, costing $38 million. Construction starts in March 2027 and should finish by the end of 2028, with some Northbourne Avenue parking removed. A community consultation is planned for early December.",
 "Pasted URL -> fetch directly, summarise page.")

rec("f", "2027-10-30T14:05:00", "Saturday",
 "what's the return policy on this one? https://shop.example/pages/returns-and-exchanges",
 [fetch("https://shop.example/pages/returns-and-exchanges",
   "Returns and exchanges\n\nYou can return unworn items within 30 days of delivery for a full refund. Items must have original tags attached. Sale items are exchange or store credit only. Return shipping is free for faulty items; otherwise customers pay return postage. Refunds are processed within 5 business days of the parcel arriving.")],
 "You can return unworn items with tags within 30 days for a full refund, though sale items are exchange or store credit only. Return postage is free for faulty items, otherwise you pay it, and refunds come through within 5 business days.",
 "Pasted URL policy page.")

rec("f", "2028-06-18T21:45:00", "Sunday",
 "is this thing any good, what are the specs https://gearshop.example/products/trail-pack-45l",
 [fetch("https://gearshop.example/products/trail-pack-45l",
   "Trail Pack 45L - $249\n\nCapacity: 45 litres. Weight: 1.4 kg. Frame: removable aluminium stay. Fabric: 210D ripstop nylon with water-resistant coating. Features: hip belt pockets, rain cover included, side compression straps, hydration sleeve. Torso fit: adjustable 43-53 cm. Warranty: 5 years.\n\nCustomer rating: 4.6 out of 5 from 312 reviews.")],
 "It's a 45 litre pack at $249 weighing 1.4 kg, with a rain cover, hip belt pockets and an adjustable torso fit. The page shows a 4.6 out of 5 rating from 312 reviews, though it doesn't say anything more about how it performs.",
 "Pasted product URL; reply stays within page content.")

rec("f", "2027-04-24T07:20:00", "Saturday",
 "when does this parkrun start and where do we meet https://parkrunevents.example/lakegeorge",
 [fetch("https://parkrunevents.example/lakegeorge",
   "Lake George parkrun\n\nEvery Saturday at 8:00am. Meet at the picnic area car park at the end of Foreshore Road from 7:30am for the new runner briefing. Free, 5 km course on a mostly flat gravel path, suitable for prams and dogs on leads. Please register once online and bring a printed barcode.")],
 "It starts at 8:00am every Saturday, meeting at the picnic area car park at the end of Foreshore Road from 7:30am. It's a free 5 km course on a mostly flat gravel path, and you'll need your printed barcode.",
 "Pasted URL; one_shot.", one_shot=True)

rec("f", "2028-09-09T17:10:00", "Saturday",
 "how long does this one bake for and at what temp? https://cookwell.example/recipes/banana-bread",
 [fetch("https://cookwell.example/recipes/banana-bread",
   "Easy Banana Bread - makes 1 loaf\n\nIngredients: 3 ripe bananas, 1/3 cup melted butter, 3/4 cup sugar, 1 egg, 1 tsp vanilla, 1 tsp baking soda, pinch of salt, 1 1/2 cups plain flour.\n\nMethod: Preheat oven to 175C and grease a loaf tin. Mash the bananas, mix in butter, sugar, egg and vanilla, then fold in the dry ingredients. Pour into the tin and bake 55 to 60 minutes, until a skewer comes out clean. Cool in the tin for 10 minutes.")],
 "It bakes at 175C for 55 to 60 minutes, until a skewer comes out clean, then cools in the tin for 10 minutes.",
 "Pasted recipe URL.")

rec("f", "2026-12-30T08:35:00", "Wednesday",
 "can you check this council notice for me and tell me which roads are closed https://council.example/notices/new-years-eve-road-closures",
 [fetch("https://council.example/notices/new-years-eve-road-closures",
   "New Year's Eve road closures\n\nThe following roads will be closed from 4pm on 31 December until 1am on 1 January: London Circuit between Constitution Avenue and Akuna Street, Northbourne Avenue between Alinga Street and Cooyong Street, and Marcus Clarke Street. Buses will be diverted and light rail will run a reduced service from 6pm. Free shuttle buses will operate from Dickson and Woden.")],
 "Closed from 4pm on 31 December until 1am are London Circuit between Constitution Avenue and Akuna Street, Northbourne Avenue between Alinga and Cooyong Streets, and Marcus Clarke Street. Buses will be diverted and light rail runs a reduced service from 6pm.",
 "Pasted URL; one_shot, statement ending.", one_shot=True)

# ---- search_news (4) ----
rec("n", "2027-01-14T12:15:00", "Thursday",
 "any news on the Canberra bus network changes",
 [news("Canberra bus network changes", [
   ("New bus network timetable starts next month", "https://canberranews.example/bus-network-changes", "Transport Canberra confirmed a revised network with higher frequencies on trunk routes, starting in February."),
   ("Commuters react to route cuts", "https://canberranews.example/bus-route-cuts", "Some suburban routes will be merged, prompting concern from residents in Gungahlin.")])],
 "A revised bus network starts in February with more frequent trunk routes. Some suburban routes are being merged, which has worried residents in Gungahlin.",
 "'any news on' -> search_news.")

rec("n", "2028-02-02T16:40:00", "Wednesday",
 "what's the latest on the interest rate decision",
 [news("interest rate decision Reserve Bank", [
   ("RBA holds cash rate at 3.60 per cent", "https://financewire.example/rba-holds-rate", "The Reserve Bank board has left the cash rate unchanged, citing inflation that remains above target."),
   ("Economists expect rate cut mid-year", "https://financewire.example/rate-cut-forecast", "Most economists now forecast a cut around mid-year if inflation continues to ease.")], time_range="week")],
 "The Reserve Bank has held the cash rate at 3.60 per cent because inflation is still above target. Most economists expect a cut around mid-year if inflation keeps easing.",
 "Latest on X -> search_news, time_range week.")

rec("n", "2027-11-16T08:05:00", "Tuesday",
 "what's happening with the Raiders this week",
 [news("Canberra Raiders", [
   ("Raiders re-sign winger on two-year deal", "https://leaguenews.example/raiders-resign-winger", "The Raiders have extended their winger's contract through 2029."),
   ("Raiders begin pre-season training", "https://leaguenews.example/raiders-preseason", "Players returned to training this week with a new fitness coach and a trial against the Rabbitohs scheduled.")], time_range="week")],
 "The Raiders have re-signed a winger on a deal through 2029, and the squad has started pre-season training with a new fitness coach. A trial against the Rabbitohs is scheduled.",
 "News, one_shot.", one_shot=True)

rec("n", "2028-01-11T20:25:00", "Tuesday",
 "anything in the news about the Australian Open draw",
 [news("Australian Open draw", [
   ("Australian Open draw revealed", "https://tennisnews.example/ao-draw-revealed", "The men's top seed faces a qualifier in round one, while the women's defending champion is in the opposite half to the second seed."),
   ("Local hopes in singles main draw", "https://tennisnews.example/ao-local-hopes", "Six Australians have been placed in the men's singles main draw.")], time_range="day")],
 "The draw's been revealed, with the men's top seed facing a qualifier in round one. The women's defending champion is in the opposite half to the second seed, and six Australians are in the men's singles main draw.",
 "News headlines.")

assert len(recs) == 30, len(recs)
anchors = [r["anchor"] for r in recs]; assert len(set(anchors)) == 30
with open("/home/charcoal/docker/trackdeck/scratchpad/training_data/chunk7/B7D.jsonl", "w") as f:
    for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
from collections import Counter
print(Counter(r["category"] for r in recs), sum(1 for r in recs if r["flags"].get("one_shot")))
