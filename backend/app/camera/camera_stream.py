import cv2
import time
from collections import deque
from app.detection.detector import track_all
from app.detection.zone_monitor import update_zone_tracking
from app.detection.concealment_monitor import update_concealment, get_concealment_flagged_ids
from app.detection import person_reid
from app.detection import item_tracker
from app.detection import incident_logger
from app.detection import pose_monitor
from app.detection import pickup_monitor
from app import profiler
from app.config import Settings

LINE_Y_RATIO = 0.5
CROSSING_COOLDOWN = 1.5

DETECT_EVERY_N_FRAMES = 2  #  CPU-only ke liye aur tez - 1 se barha kar 2 kiya

# Incident video clip ke liye: item ghaib hone se PEHLE aur BAAD ka kitna
# footage shamil karna hai. Total clip lagbhag PRE + POST second ki hogi,
# jiske beech mein wo lamha aayega jab item asal mein ghaib hua tha.
PRE_INCIDENT_SECONDS = 5
POST_INCIDENT_SECONDS = 3

# Buffer itna bara rakhna zaroori hai ke jab tak POST wala hissa export
# hone ke liye ready ho (disappearance ke POST_INCIDENT_SECONDS baad),
# tab tak PRE wala purana hissa (disappearance se PRE_INCIDENT_SECONDS
# pehle) bhi buffer mein maujood ho. Isliye PRE + POST + thora extra
# margin (timing jitter ke liye) rakha hai.
VIDEO_BUFFER_SECONDS = PRE_INCIDENT_SECONDS + POST_INCIDENT_SECONDS + 4

# Reference resolution jis par font/line sizes originally design kiye gaye the
# (0.55 font scale, 2px thickness). Har camera ki apni resolution ho sakti hai
# (Device 0 vs Device 1 alag), aur agar text ek fixed pixel size mein draw
# karein to bari-resolution wali camera ka text frontend mein zyada chhota
# dikhta hai (kyunke usay barabar size ke box mein fit karne ke liye zyada
# scale-down hota hai). Isliye frame ki height ke hisab se scale nikalte hain.
REFERENCE_FRAME_HEIGHT = 480


def _new_camera_state():
    """Har naye camera ke liye khali/default state banata hai."""
    return {
        "capture": None,
        "device_index": 0,
        # "camera" = live webcam, "file" = recorded mp4 chal raha hai
        "source_type": "camera",
        "loop_video": True,   # file khatam hote hi shuru se dobara chale
        "is_paused": False,
        "last_frame_bytes": None,
        "current_person_count": 0,
        "unique_visitor_ids": set(),
        "entry_count": 0,
        "exit_count": 0,
        "track_history": {},
        "last_crossing_time": {},
        "active_alerts": [],
        "active_concealment_alerts": [],
        # Har camera ka apna zone — shuru mein Settings se copy hota hai,
        # baad mein frontend se adjust ho sakta hai (set_zone() dekhein)
        "zone_ratios": {
            "x1": Settings.ZONE_X1_RATIO,
            "y1": Settings.ZONE_Y1_RATIO,
            "x2": Settings.ZONE_X2_RATIO,
            "y2": Settings.ZONE_Y2_RATIO,
        },
        "zone_enabled": True,
        # Speed optimization: har frame detect nahi karte, purana result reuse karte hain
        "frame_counter": 0,
        "last_persons": [],
        "last_items": [],
        # Speed optimization: har track ID ka global_id ek dafa nikal kar yaad rakhte hain
        "global_id_cache": {},
        # Speed optimization: har detection par pose nahi chalate, pichla pose
        # kuch dair yaad rakhte hain (pickup_monitor.refresh_poses dekhein)
        "pose_cache": {},
        # Rolling video buffer: (timestamp, jpg_bytes) tuples, purane->naye.
        # Har asal frame yahan store hota hai (chahe detection chali ho ya
        # na ho), taake sustained-concealment confirm hote hi pichle
        # VIDEO_BUFFER_SECONDS ka clip nikala ja sake. JPEG bytes store
        # karte hain (raw frame nahi) taake RAM usage kam rahe.
        "frame_buffer": deque(),
        # Confirmed incidents jinke video ka "POST" hissa abhi ban raha hai -
        # yeh yahan wait karte hain jab tak enough future frames record na
        # ho jayen, phir export ho kar yahan se hat jate hain.
        # Format: {"incident_id", "alert", "export_at"}
        "pending_video_exports": [],
    }


# Sab cameras yahan store honge — abhi sirf 1 use ho raha hai (purana behaviour)
cameras = {
    1: _new_camera_state()
}


def _get_state(cam_id):
    if cam_id not in cameras:
        cameras[cam_id] = _new_camera_state()
    return cameras[cam_id]


def _zone_box_px(state, frame_width, frame_height):
    """Camera ke apne zone_ratios se actual pixel coordinates nikalta hai."""
    r = state["zone_ratios"]
    x1 = int(frame_width * r["x1"])
    y1 = int(frame_height * r["y1"])
    x2 = int(frame_width * r["x2"])
    y2 = int(frame_height * r["y2"])
    return x1, y1, x2, y2


def set_zone(cam_id, x1, y1, x2, y2):
    """Frontend se naye zone ratios (0.0 - 1.0) save karta hai is camera ke liye."""
    state = _get_state(cam_id)
    state["zone_ratios"] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def set_zone_enabled(cam_id, enabled):
    """Zone ko on/off karta hai (remove button ke liye)."""
    state = _get_state(cam_id)
    state["zone_enabled"] = enabled


def start_camera(cam_id=1, device_index=None):
    state = _get_state(cam_id)

    if device_index is not None:
        state["device_index"] = device_index

    if state["capture"] is None or not state["capture"].isOpened():
        state["capture"] = cv2.VideoCapture(state["device_index"])

        # Speed optimization: webcam ko explicitly chhoti resolution + MJPG
        # format pe set karo. Agar yeh na kiya jaye to bohat se webcams apni
        # default (kabhi kabhi 720p/1080p) resolution pe frames dete hain,
        # jo decode/resize/encode sab ko slow kar deta hai - chahe YOLO khud
        # chhote imgsz pe chale. MJPG bhi USB webcams par capture ko tez karta hai.
        state["capture"].set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        state["capture"].set(cv2.CAP_PROP_FRAME_WIDTH, 480)
        state["capture"].set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        state["capture"].set(cv2.CAP_PROP_FPS, 30)

    state["is_paused"] = False
    return state["capture"].isOpened()


def start_camera_from_file(cam_id, file_path, loop=True):
    """
    Live webcam ki jagah ek recorded .mp4 file ko "camera" ki tarah chalata
    hai - baaki poora system (YOLO, pose, concealment, dashboard) isay
    normal camera hi samjhega, kyunke generate_frames() same tarah frames
    padhta hai chahe source webcam ho ya file.

    loop=True (default): video khatam hote hi khud shuru se dobara chalti
    hai - taake ek hi "chori" wali clip baar baar test ki ja sake bina
    dobara button dabaye.
    """
    state = _get_state(cam_id)

    if state["capture"] is not None:
        state["capture"].release()

    state["capture"] = cv2.VideoCapture(file_path)
    state["source_type"] = "file"
    state["loop_video"] = loop
    state["is_paused"] = False

    opened = state["capture"].isOpened()
    if not opened:
        state["capture"] = None
    return opened


def pause_camera(cam_id=1):
    state = _get_state(cam_id)
    state["is_paused"] = True


def resume_camera(cam_id=1):
    state = _get_state(cam_id)
    state["is_paused"] = False


def stop_camera(cam_id=1):
    state = _get_state(cam_id)
    if state["capture"] is not None:
        state["capture"].release()
    state["capture"] = None
    state["source_type"] = "camera"
    state["is_paused"] = False
    state["last_frame_bytes"] = None
    state["current_person_count"] = 0


def draw_tracks(frame, persons, items, zone_box=None, zone_enabled=True):
    # Zone ab video ke andar draw nahi hoti — frontend ka adjustable overlay hi
    # zone dikhata hai. Yahan zone_box sirf detection ke liye use hota hai (generate_frames mein).

    # Frame ki apni resolution ke hisab se font/line ko scale karo (upar
    # REFERENCE_FRAME_HEIGHT ka comment dekhein) - taake Camera 1 aur
    # Camera 2 ka label size, screen par dikhte waqt, barabar lage chahe
    # unki native camera resolution alag ho.
    frame_height = frame.shape[0]
    scale = frame_height / REFERENCE_FRAME_HEIGHT
    font_scale = max(0.35, 0.55 * scale)
    item_font_scale = max(0.32, 0.5 * scale)
    box_thickness = max(1, round(2 * scale))
    text_thickness = max(1, round(2 * scale))

    for track in persons:
        x1, y1, x2, y2 = track["x1"], track["y1"], track["x2"], track["y2"]
        track_id = track["id"]
        is_suspicious = track.get("suspicious", False)
        is_concealment = track.get("concealment_flag", False)
        global_id = track.get("global_id")

        color = (0, 0, 255) if (is_suspicious or is_concealment) else (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, box_thickness)

        if is_concealment:
            label = f"ID {track_id} (G{global_id}) - CONCEALMENT ALERT"
        elif is_suspicious:
            label = f"ID {track_id} (G{global_id}) - WRONG ACTIVITY"
        else:
            dwell = track.get("dwell_time", 0)
            label = f"ID {track_id} (G{global_id})" + (f" ({dwell}s)" if dwell > 0 else "")

        cv2.putText(frame, label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, text_thickness)

        # Step 1 (MediaPipe): kalai/kandhe/kolhe ke points peele dots mein dikhao
        pose = track.get("pose")
        if pose:
            for point in pose.values():
                if point is not None:
                    cv2.circle(frame, point, max(3, box_thickness * 2), (0, 255, 255), -1)

    for item in items:
        x1, y1, x2, y2 = item["x1"], item["y1"], item["x2"], item["y2"]

        # Step 2: agar kisi ke haath mein hai to magenta, warna purana rang
        held_by = item.get("held_by")
        item_color = (255, 0, 255) if held_by is not None else (255, 200, 0)
        item_label = item["class_name"]
        if held_by is not None:
            item_label += f" HELD by G{held_by}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), item_color, box_thickness)
        cv2.putText(frame, item_label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, item_font_scale, item_color, text_thickness)

    return frame


def check_line_crossing(state, tracks, line_y):
    now = time.time()

    for track in tracks:
        track_id = track["id"]
        cy = (track["y1"] + track["y2"]) // 2

        if track_id in state["track_history"]:
            prev_cy = state["track_history"][track_id]
            last_time = state["last_crossing_time"].get(track_id, 0)

            if now - last_time > CROSSING_COOLDOWN:
                if prev_cy < line_y <= cy:
                    state["entry_count"] += 1
                    state["last_crossing_time"][track_id] = now
                elif prev_cy > line_y >= cy:
                    state["exit_count"] += 1
                    state["last_crossing_time"][track_id] = now

        state["track_history"][track_id] = cy


def update_alerts(state, tracks):
    state["active_alerts"] = []
    for track in tracks:
        if track.get("suspicious", False):
            state["active_alerts"].append({
                "id": track["id"],
                "global_id": track.get("global_id"),
                "dwell_time": track.get("dwell_time", 0),
                "message": f"Person ID {track['id']} (Global {track.get('global_id')}) — {track.get('dwell_time', 0)}s in monitored zone"
            })


def apply_person_reid(frame, persons, state):
    """Har person ko ek Global ID deta hai, aur agar doosre camera se pehle se flagged hai to yahan bhi suspicious mark karta hai.
    Speed ke liye: agar is track_id ka global_id pehle nikal chuke hain, to dobara signature nahi nikalte."""
    cache = state["global_id_cache"]

    for track in persons:
        track_id = track["id"]

        if track_id in cache:
            global_id = cache[track_id]
        else:
            x1, y1, x2, y2 = track["x1"], track["y1"], track["x2"], track["y2"]
            signature, person_crop = person_reid.extract_signature(frame, x1, y1, x2, y2)
            face_encoding = person_reid.extract_face_encoding(frame, x1, y1, x2, y2)
            global_id = person_reid.match_or_register(signature, person_crop, face_encoding)
            cache[track_id] = global_id

        track["global_id"] = global_id

        # Agar ye insaan pehle kisi camera mein flag ho chuka hai, to yahan bhi turant dikhao
        was_suspicious, was_concealment = person_reid.is_flagged(global_id)
        if was_suspicious:
            track["suspicious"] = True

    return persons


def _handle_new_concealment_incidents(new_alerts, state, cam_id):
    """
    Naye CONFIRMED concealment incidents (sustained threshold cross kar
    chuke) ko yahan turant export NAHI karte - kyunke video mein
    "disappearance ke POST_INCIDENT_SECONDS baad" ka footage bhi chahiye,
    jo abhi record hi nahi hua. Isliye inhe "pending_video_exports" mein
    daal dete hain; asal export _flush_ready_video_exports() karega jab
    itna waqt guzar jaye.
    """
    for alert in new_alerts:
        incident_id = f"cam{cam_id}_g{alert['global_id']}_{int(alert['disappeared_at'] * 1000)}"
        state["pending_video_exports"].append({
            "incident_id": incident_id,
            "alert": alert,
            "export_at": alert["disappeared_at"] + POST_INCIDENT_SECONDS,
        })


def _flush_ready_video_exports(state, cam_id):
    """
    Jin pending incidents ka POST_INCIDENT_SECONDS wala intezaar poora ho
    chuka hai, unke liye ab poora clip (PRE + disappearance + POST) frame_buffer
    se nikal kar .mp4 save karta hai, aur metadata bhi (ek sath, video_path
    ke sath) log karta hai. Har frame par call hota hai (halka operation hai).
    """
    if not state["pending_video_exports"]:
        return

    now = time.time()
    still_pending = []

    for entry in state["pending_video_exports"]:
        if now < entry["export_at"]:
            still_pending.append(entry)
            continue

        alert = entry["alert"]
        window_start = alert["disappeared_at"] - PRE_INCIDENT_SECONDS
        window_end = alert["disappeared_at"] + POST_INCIDENT_SECONDS

        clip_frames = [
            (ts, jpg) for ts, jpg in state["frame_buffer"]
            if window_start <= ts <= window_end
        ]

        video_path = incident_logger.save_incident_clip(clip_frames, entry["incident_id"])

        incident_logger.log_incident({
            "incident_id": entry["incident_id"],
            "camera_id": cam_id,
            "global_id": alert["global_id"],
            "person_id": alert["person_id"],
            "item": alert["item"],
            "message": alert["message"],
            "disappeared_at_time": time.strftime("%Y-%m-%d %I:%M:%S %p", time.localtime(alert["disappeared_at"])),
            "confirmed_at_time": time.strftime("%Y-%m-%d %I:%M:%S %p", time.localtime(alert["created_at"])),
            "video_path": video_path,
        })

    state["pending_video_exports"] = still_pending


def generate_frames(cam_id=1):
    state = _get_state(cam_id)

    while True:
        if state["capture"] is None or not state["capture"].isOpened():
            break

        if state["is_paused"]:
            if state["last_frame_bytes"] is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + state["last_frame_bytes"] + b'\r\n')
            time.sleep(0.1)
            continue

        with profiler.stage(cam_id, "read"):
            ret, frame = state["capture"].read()

        if not ret:
            if state["source_type"] == "file" and state["loop_video"]:
                # Video file khatam ho gayi - shuru se dobara chalao (live
                # camera ke liye yeh kabhi True nahi hota, wahan waisa hi
                # rukega jaisa pehle tha)
                state["capture"].set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            break

        height, width = frame.shape[:2]
        line_y = int(height * LINE_Y_RATIO)
        zone_box = _zone_box_px(state, width, height)

        state["frame_counter"] += 1
        # Multiple cameras ho to unka detection ek hi waqt pe na chale
        # (warna CPU pe ek sath "burst" aata hai aur stutter zyada mehsoos
        # hota hai) - isliye har camera ko cam_id ke hisab se alag "phase"
        # diya hai, taake unka YOLO turn baari-baari (staggered) aaye.
        run_detection = (state["frame_counter"] % DETECT_EVERY_N_FRAMES) == (cam_id % DETECT_EVERY_N_FRAMES)

        if run_detection:
            with profiler.stage(cam_id, "yolo"):
                persons, items = track_all(frame, cam_id)

            # Jo track IDs ab maujood nahi, unka cached global_id bhi hata do
            current_ids = {p["id"] for p in persons}
            stale_ids = [tid for tid in state["global_id_cache"] if tid not in current_ids]
            for tid in stale_ids:
                del state["global_id_cache"][tid]

            # NOTE: item_tracker.cleanup_item() yahan JAAN-BOOJH KAR nahi
            # bulaya ja raha - woh update_concealment() ke BAAD chalega
            # (neeche dekhein). Pehle yahan hota tha, jo ek bara bug tha:
            # concealment_monitor ko "kya yeh item personal tha?" check
            # karne se PEHLE hi origin record mit chuka hota tha, isliye
            # har item (chahe genuinely personal ho) hamesha "None" origin
            # dikhta tha aur false concealment alert ban jati thi.
            current_item_ids = {it["id"] for it in items}

            state["current_person_count"] = len(persons)

            for p in persons:
                state["unique_visitor_ids"].add(p["id"])

            check_line_crossing(state, persons, line_y)

            if state["zone_enabled"]:
                persons = update_zone_tracking(persons, zone_box, Settings.SUSPICIOUS_DWELL_SECONDS)

            # ---- Cross-Camera Re-ID: har person ko Global ID do, aur purane flags check karo ----
            with profiler.stage(cam_id, "reid"):
                persons = apply_person_reid(frame, persons, state)

            # Step 1+2 (MediaPipe): pose sirf unn logon par jinke qareeb koi item ho
            # (CPU bachane ke liye), phir dekho kis ke haath mein item hai
            with profiler.stage(cam_id, "pose+pickup"):
                pickup_monitor.refresh_poses(
                    frame, persons, items, state["pose_cache"],
                    lambda f, p: pose_monitor.detect_pose(f, p, cam_id),
                )
                pickup_monitor.update_pickups(persons, items, cam_id)

            # ZAROORI: item registration ab yahan, apply_person_reid ke BAAD
            # hoti hai - kyunke item_tracker ab "person['global_id']" use
            # karta hai (personal-item reclaim feature ke liye). Pehle yeh
            # ulta order tha (registration pehle, reid baad mein), isliye
            # global_id hamesha None milta tha aur koi bhi item "personal"
            # mark hi nahi ho pata tha, chahe person kitna bhi qareeb ho.
            for item in items:
                item_tracker.register_item_if_new(item, persons)

            update_alerts(state, persons)

            # Jo is camera mein NAYA suspicious hua, usay registry mein bhi note karo
            for p in persons:
                if p.get("suspicious", False):
                    person_reid.mark_suspicious(p["global_id"], True)

            # concealment_monitor ab do cheezein deta hai:
            #  - active list (jo abhi on-screen dikhni chahiye)
            #  - new_alerts (sirf woh jo ISI call mein "sustained threshold"
            #    cross karke CONFIRM hui - inhi par video/log banega, taake
            #    ek incident ka video/log baar baar na bane)
            with profiler.stage(cam_id, "conceal"):
                state["active_concealment_alerts"], new_concealment_alerts = update_concealment(persons, items)

            if new_concealment_alerts:
                _handle_new_concealment_incidents(new_concealment_alerts, state, cam_id)

            # Ab (aur sirf ab) jo items frame mein nahi rahe, unki origin
            # memory se hata do - concealment_monitor upar apna kaam kar
            # chuka hai, ab record mitana safe hai.
            stale_item_ids = [iid for iid in item_tracker.item_origins if iid not in current_item_ids]
            for iid in stale_item_ids:
                item_tracker.cleanup_item(iid)

            # Har frame pe taaza check: kis person (GLOBAL ID se) ki koi
            # concealment alert abhi active hai -> uski ID box red hogi
            # (draw_tracks mein), warna green. Global ID use karne se yeh
            # cross-camera bhi kaam karta hai: Camera 1 mein chori pakri jaye
            # to wahi banda Camera 2 mein bhi turant red dikhega, aur jab
            # item wapis aaye to dono jagah green wapis ho jayega.
            concealment_flagged_ids = get_concealment_flagged_ids()
            for p in persons:
                p["concealment_flag"] = p["global_id"] in concealment_flagged_ids

            # Pura processed result save kar lo - agle skip-frames isi ko
            # dobara istemal karenge (koi dobara processing ki zaroorat nahi,
            # kyunke sab attributes - global_id, suspicious, concealment_flag -
            # already inhi dicts ke andar save ho chuke hain)
            state["last_persons"] = persons
            state["last_items"] = items
        else:
            # Is frame pe YOLO nahi chalaya - pichla PURA-PROCESSED result hi
            # reuse karo (zone/reid/concealment sab dobara chalane ki zaroorat
            # nahi, woh already in dicts mein save hai)
            persons, items = state["last_persons"], state["last_items"]

        with profiler.stage(cam_id, "draw"):
            frame = draw_tracks(frame, persons, items, zone_box, state["zone_enabled"])

        with profiler.stage(cam_id, "encode"):
            success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])

        if not success:
            continue

        state["last_frame_bytes"] = buffer.tobytes()

        # Rolling video buffer: har asal frame yahan jaata hai (chahe
        # detection chali ho ya na ho), taake sustained-concealment confirm
        # hote hi disappearance ke aas-paas (PRE + POST) ka clip nikala ja sake.
        now = time.time()
        state["frame_buffer"].append((now, state["last_frame_bytes"]))
        while state["frame_buffer"] and (now - state["frame_buffer"][0][0]) > VIDEO_BUFFER_SECONDS:
            state["frame_buffer"].popleft()

        # Jo incidents ka POST-wait poora ho chuka hai, unka video ab export karo
        _flush_ready_video_exports(state, cam_id)

        profiler.frame_done(cam_id)

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + state["last_frame_bytes"] + b'\r\n')