import time
from app.detection import item_tracker

item_last_seen = {}
concealment_history = []
recent_alerts = []
last_alert_time = {}

# Jab item pehli dafa gayab hota hai to turant alert nahi banti - pehle
# yahan "pending" mein daal dete hain. Agar item itni dair (SUSTAINED_
# CONCEALMENT_SECONDS) tak continuously gayab raha (turant wapis nahi
# aaya), tabhi woh "confirmed" alert banti hai. Isse false alarms kam
# hote hain (jaise YOLO ka koi ek frame miss ho jana).
# Key format: "{global_id}_{item_class}" -> {"since": timestamp, ...}
pending_concealments = {}

# Yaad rakhta hai kaunsi concealment alert is waqt "active" (on-screen) hai.
# Key ab GLOBAL ID se banti hai (local per-camera ID se nahi) - taake yeh
# cross-camera kaam kare (jo banda Camera 1 mein flag hua wahi Camera 2 mein
# bhi red dikhe, kyunke Global ID sab cameras mein same rehta hai).
# Key format: "{global_id}_{item_class}"  ->  True/False
active_concealments = {}

ALERT_DISPLAY_SECONDS = 60
ALERT_COOLDOWN_SECONDS = 15
SUSTAINED_CONCEALMENT_SECONDS = 2.0  # itni dair continuously gayab rahe tab confirm ho

# NOTE: pehle yeh ek FIXED "NEARBY_DISTANCE = 20" (pixels) tha - jo bohat
# tight tha. Agar camera door thi ya bottle thori si bhi table pe alag
# (person ke box se 20px se zyada) thi, to "qareeb" hi count nahi hoti thi,
# isliye pending concealment kabhi banti hi nahi thi (asal chori bhi miss
# ho jati thi). Ab yeh item_tracker.py jaisa hi, PERSON KE SIZE ke hisab
# se relative hai - taake camera chahe door ho ya qareeb, sahi kaam kare.
NEARBY_DISTANCE_RATIO = 0.6
NEARBY_DISTANCE_MIN = 40  # bohat chhoti/door detection ke liye minimum margin


def _is_near(cx, cy, person):
    """Kya (cx, cy) point is person ke box ke (size-relative) margin ke andar hai?"""
    px1, py1, px2, py2 = person["x1"], person["y1"], person["x2"], person["y2"]
    person_w = px2 - px1
    person_h = py2 - py1
    margin = max(NEARBY_DISTANCE_MIN, max(person_w, person_h) * NEARBY_DISTANCE_RATIO)
    return (px1 - margin) <= cx <= (px2 + margin) and (py1 - margin) <= cy <= (py2 + margin)


def update_concealment(persons, items):
    global item_last_seen, concealment_history, recent_alerts, last_alert_time, active_concealments, pending_concealments

    now = time.time()
    current_item_ids = set()

    for item in items:
        current_item_ids.add(item["id"])
        item_last_seen[item["id"]] = {
            "class_name": item["class_name"],
            "cx": (item["x1"] + item["x2"]) // 2,
            "cy": (item["y1"] + item["y2"]) // 2,
        }

    # Naye alerts jo ISI call mein "confirm" hue - camera_stream.py isay use
    # karega taake incident metadata log kare aur video clip save kare
    # (sirf EK dafa, jab pehli baar confirm ho, dobara nahi).
    new_alerts = []

    # ---- STEP 1: Reappearance check ----
    # Agar kisi (Global ID) person ke paas pehle "concealment" alert active
    # thi, aur ab wahi type ka item dobara unke qareeb nazar aa gaya hai
    # (chahe yeh kisi bhi camera mein ho, kyunke Global ID sab cameras mein
    # same hai) - to iska matlab shayad chori nahi thi. Active alert hata do.
    for item in items:
        item_class = item["class_name"]
        icx = (item["x1"] + item["x2"]) // 2
        icy = (item["y1"] + item["y2"]) // 2

        for person in persons:
            if _is_near(icx, icy, person):
                global_id = person["global_id"]
                cooldown_key = f"{global_id}_{item_class}"

                # NOTE: Pehle yahan "pending" bhi turant clear ho jati thi
                # jaise hi item ek dafa bhi dobara nazar aata - lekin item
                # chupate waqt (haath mein le kar jeb tak) YOLO ka detection
                # khud hi flicker karta hai (ek-do frame ke liye halka sa
                # dikh jana), jis se asal concealment ka 2-second countdown
                # baar baar reset ho kar kabhi complete hi nahi hota tha.
                # Ab PENDING ko yahan clear NAHI karte - woh apna 2-second
                # countdown continuously chalata rahega chahe beech mein
                # flicker ho. Sirf CONFIRMED (active_concealments) wapis
                # green hoti hai jab item genuinely dobara dikhe.
                if active_concealments.get(cooldown_key):
                    recent_alerts = [
                        a for a in recent_alerts
                        if not (a["global_id"] == global_id and a["item"] == item_class)
                    ]
                    active_concealments[cooldown_key] = False

                    concealment_history.append({
                        "time": time.strftime("%I:%M:%S %p"),
                        "message": f"✅ {item_class} reappeared near Person ID {person['id']} (Global {global_id}) — concealment alert cleared"
                    })
                break

    # ---- STEP 2: Disappearance check -> PENDING mein daalo (turant alert nahi) ----
    disappeared_ids = [tid for tid in item_last_seen if tid not in current_item_ids]

    for tid in disappeared_ids:
        last = item_last_seen[tid]

        for person in persons:
            if _is_near(last["cx"], last["cy"], person):
                # Agar yeh item person ka apna tha (jaise apna mobile),
                # to yeh chori nahi — alert mat banao, bas aage badh jao.
                origin = item_tracker.get_item_origin(tid)
                if origin == "personal":
                    break

                global_id = person["global_id"]
                cooldown_key = f"{global_id}_{last['class_name']}"

                # Sirf PEHLI dafa gayab hone par pending shuru karo - agar
                # pehle se pending hai to uska "since" time overwrite mat
                # karo (warna item kabhi bhi threshold cross nahi karega).
                if cooldown_key not in pending_concealments:
                    pending_concealments[cooldown_key] = {
                        "since": now,
                        "person_id": person["id"],
                        "global_id": global_id,
                        "item_class": last["class_name"],
                    }

                break

        del item_last_seen[tid]

    # ---- STEP 3: Pending concealments jo threshold cross kar chuke - CONFIRM karo ----
    for cooldown_key, pending in list(pending_concealments.items()):
        if now - pending["since"] < SUSTAINED_CONCEALMENT_SECONDS:
            continue  # abhi itni dair nahi hui - abhi bhi sirf "pending"

        # Threshold cross ho gayi - is pending ko final decide kar do
        # (chahe cooldown ki wajah se skip ho jaye, pending se hata do -
        # dobara har frame check karne ki zaroorat nahi).
        del pending_concealments[cooldown_key]

        last_time = last_alert_time.get(cooldown_key, 0)
        if now - last_time <= ALERT_COOLDOWN_SECONDS:
            continue  # thodi dair pehle hi isi type ki alert ban chuki thi

        global_id = pending["global_id"]
        item_class = pending["item_class"]
        person_id = pending["person_id"]

        message = f"⚠ {item_class} disappeared near Person ID {person_id} (Global {global_id}) — Possible Concealment"

        alert = {
            "person_id": person_id,
            "global_id": global_id,
            "item": item_class,
            "message": message,
            "created_at": now,               # jab CONFIRM hui (disappearance + sustained threshold)
            "disappeared_at": pending["since"],  # jab item ASAL mein ghaib hua tha
        }

        recent_alerts.append(alert)
        new_alerts.append(alert)

        concealment_history.append({
            "time": time.strftime("%I:%M:%S %p"),
            "message": message
        })

        last_alert_time[cooldown_key] = now
        active_concealments[cooldown_key] = True

    recent_alerts = [a for a in recent_alerts if now - a["created_at"] < ALERT_DISPLAY_SECONDS]

    # Jin alerts ka on-screen display time khatam ho gaya, unhe bhi
    # "not active" mark kar do (taake active_concealments state sahi rahe)
    still_active_keys = {f"{a['global_id']}_{a['item']}" for a in recent_alerts}
    for key in list(active_concealments.keys()):
        if active_concealments[key] and key not in still_active_keys:
            active_concealments[key] = False

    return recent_alerts, new_alerts


def get_concealment_flagged_ids():
    """
    Un GLOBAL IDs ka set deta hai jinki koi na koi concealment alert
    is waqt active hai — chahe wo kisi bhi camera mein trigger hui ho.
    camera_stream.py isay har camera mein use karega taake us person ki
    ID box (uska Global ID match kar ke) red/green dikhai ja sake.
    """
    return {a["global_id"] for a in recent_alerts}