"""
item_tracker.py

Purpose:
--------
Decide, for every item YOLO detects (bottle, mobile, etc.), whether it
belongs to the STORE (was sitting on a shelf) or to a PERSON (unke apna
personal item, jo woh khud camera mein le kar aaye).

Is version mein 3 improvements hain (pehle ke simple "sirf first frame
dekho, fixed 80px radius" wale tareeqe se):

1. PROXIMITY ab person ke box ke SIZE ke hisab se RELATIVE hai (fixed
   pixel value nahi) - taake camera chahe door (CCTV) ho ya bohot qareeb
   (webcam), "qareeb" ka matlab dono cases mein sahi rahe.

2. GRACE PERIOD: agar item pehli dafa dikhte hi koi person qareeb nahi
   mila, turant "store" mat bolo - thori dair (GRACE_PERIOD_SECONDS)
   dekho, ho sakta hai person abhi usi exact frame mein detect na hua ho
   (timing race condition).

3. RECLAIM WINDOW: agar ek "personal" item ki track ID switch ho jaye
   (jaise insaan baithte waqt bottle thori dair occlude ho gayi aur naya
   ID mila), to naya ID bhi turant "personal" maana jayega - agar wo usi
   insaan (Global ID) ke paas, usi item-class ka, thori dair
   (RECLAIM_WINDOW_SECONDS) ke andar wapis dikhe.

Is file ka doosra zaroori hissa camera_stream.py mein hai: waha
item_tracker.cleanup_item() ab update_concealment() ke BAAD call hota hai
(pehle GHALTI se pehle hota tha) - taake concealment_monitor ko origin
check karne ka mauka mile ISSE PEHLE ke record mit jaye.
"""

import math
import time

# item_track_id -> {"origin": "store"/"personal", "global_id": int|None, "class_name": str}
item_origins = {}

# item_track_id -> {"first_seen": timestamp, "class_name": str}
# (abhi decide nahi hua - "grace period" mein hai)
pending_items = {}

# "{global_id}_{class_name}" -> {"lost_at": timestamp}
# Recently disappeared PERSONAL items - taake track-ID switch hone par
# dobara "apna" pehchana ja sake.
recently_lost_personal = {}

# Kitna percent (person ke box ke bare dimension ka) "qareeb" mana jaye.
# Fixed pixel value ki jagah relative rakha hai taake camera door/qareeb
# dono situations mein sahi kaam kare.
PROXIMITY_RATIO = 0.6

# Naya item dikhte hi turant "store" mat bolo - itni dair wait karo
# (ho sakta hai person abhi usi frame mein detect na hua ho).
GRACE_PERIOD_SECONDS = 1.5

# Personal item ki track ID switch hone par itni dair tak "apna wapis mil
# sakta hai" wali window khuli rakho.
RECLAIM_WINDOW_SECONDS = 4.0


def _get_center(detection):
    """
    detection = a dict like {"id": 5, "x1":.., "y1":.., "x2":.., "y2":..}
    -> returns the (center_x, center_y) point.
    """
    cx = (detection["x1"] + detection["x2"]) / 2
    cy = (detection["y1"] + detection["y2"]) / 2
    return (cx, cy)


def _distance(point_a, point_b):
    """Straight-line distance between two (x, y) points."""
    return math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])


def _is_near_person(item, person):
    """Person ke box ke SIZE ke hisab se 'qareeb' decide karta hai - fixed
    pixel radius ki jagah, taake camera distance se independent rahe."""
    item_center = _get_center(item)
    person_center = _get_center(person)
    person_w = person["x2"] - person["x1"]
    person_h = person["y2"] - person["y1"]
    threshold = max(person_w, person_h) * PROXIMITY_RATIO
    return _distance(item_center, person_center) < threshold


def _cleanup_expired_reclaims():
    now = time.time()
    expired = [k for k, v in recently_lost_personal.items() if now - v["lost_at"] > RECLAIM_WINDOW_SECONDS]
    for k in expired:
        del recently_lost_personal[k]


def register_item_if_new(item, persons):
    """
    Call this once per frame, for every item in the `items` list that
    detector.py's track_all() returned.

    Jab tak decision FINAL na ho jaye (store/personal), yeh function har
    detection-frame par dobara try karta hai (pending state mein).
    """
    item_id = item["id"]

    if item_id in item_origins:
        return  # already decided (finalized), don't re-decide

    now = time.time()
    class_name = item["class_name"]

    near_global_id = None
    for person in persons:
        if _is_near_person(item, person):
            near_global_id = person.get("global_id")
            break

    if near_global_id is not None:
        # ---- Reclaim check: kahin yeh kisi abhi-abhi gayab hui apni item
        # ka continuation to nahi (track ID switch ki wajah se)? ----
        reclaim_key = f"{near_global_id}_{class_name}"
        recently_lost_personal.pop(reclaim_key, None)

        item_origins[item_id] = {
            "origin": "personal",
            "global_id": near_global_id,
            "class_name": class_name,
        }
        pending_items.pop(item_id, None)
        return

    # Koi person qareeb nahi mila - turant "store" mat bolo, pehle
    # thori dair (grace period) dekho.
    if item_id not in pending_items:
        pending_items[item_id] = {"first_seen": now, "class_name": class_name}
        return

    if now - pending_items[item_id]["first_seen"] >= GRACE_PERIOD_SECONDS:
        item_origins[item_id] = {
            "origin": "store",
            "global_id": None,
            "class_name": class_name,
        }
        pending_items.pop(item_id, None)
    # warna abhi bhi "pending" hi rahega, agli baar dobara try hoga


def get_item_origin(item_id):
    """
    Returns "store", "personal", or None if this item_id was never
    finalized (ya to abhi register hi nahi hua, ya "pending"/grace-period
    mein hai).
    """
    data = item_origins.get(item_id)
    return data["origin"] if data else None


def cleanup_item(item_id):
    """
    Call this when an item's track is lost (frame se permanently gayab).

    Agar yeh "personal" item tha, to iski yaad "recently_lost_personal"
    mein rakh dete hain - taake agar isi insaan (Global ID) ke paas thori
    dair mein isi type ka item NAYI track ID ke sath dobara dikhe (jaise
    occlusion/sitting down ki wajah se ID switch hui ho), to usay turant
    "apna" pehchana ja sake, dobara "store" na bane.

    ZAROORI: yeh function camera_stream.py mein update_concealment() ke
    BAAD call hona chahiye, taake concealment_monitor origin check karne
    ka mauka paye ISSE PEHLE ke yeh record mit jaye.
    """
    data = item_origins.pop(item_id, None)
    pending_items.pop(item_id, None)

    if data and data["origin"] == "personal" and data["global_id"] is not None:
        reclaim_key = f"{data['global_id']}_{data['class_name']}"
        recently_lost_personal[reclaim_key] = {"lost_at": time.time()}

    _cleanup_expired_reclaims()