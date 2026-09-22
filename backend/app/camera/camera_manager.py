import cv2
import time
from app.detection.detector import track_all
from app.detection.zone_monitor import get_zone_coordinates, update_zone_tracking
from app.detection.concealment_monitor import update_concealment
from app.config import Settings

camera = None
is_paused = False
last_frame_bytes = None
current_person_count = 0
unique_visitor_ids = set()

entry_count = 0
exit_count = 0
track_history = {}
last_crossing_time = {}
CROSSING_COOLDOWN = 1.5

LINE_Y_RATIO = 0.5

active_alerts = []
active_concealment_alerts = []


def start_camera():
    global camera, is_paused
    if camera is None or not camera.isOpened():
        camera = cv2.VideoCapture(0)
    is_paused = False
    return camera.isOpened()


def pause_camera():
    global is_paused
    is_paused = True


def resume_camera():
    global is_paused
    is_paused = False


def stop_camera():
    global camera, is_paused, last_frame_bytes, current_person_count
    if camera is not None:
        camera.release()
    camera = None
    is_paused = False
    last_frame_bytes = None
    current_person_count = 0


def draw_tracks(frame, persons, items, zone_box):
    zx1, zy1, zx2, zy2 = zone_box
    cv2.rectangle(frame, (zx1, zy1), (zx2, zy2), (255, 165, 0), 2)
    cv2.putText(frame, "MONITORED ZONE", (zx1, zy1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 165, 0), 2)

    for track in persons:
        x1, y1, x2, y2 = track["x1"], track["y1"], track["x2"], track["y2"]
        track_id = track["id"]
        is_suspicious = track.get("suspicious", False)

        color = (0, 0, 255) if is_suspicious else (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        if is_suspicious:
            label = f"ID {track_id} - WRONG ACTIVITY"
        else:
            dwell = track.get("dwell_time", 0)
            label = f"ID {track_id}" + (f" ({dwell}s)" if dwell > 0 else "")

        cv2.putText(frame, label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    for item in items:
        x1, y1, x2, y2 = item["x1"], item["y1"], item["x2"], item["y2"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
        cv2.putText(frame, item["class_name"], (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)

    return frame


def check_line_crossing(tracks, line_y):
    global entry_count, exit_count, track_history, last_crossing_time

    now = time.time()

    for track in tracks:
        track_id = track["id"]
        cy = (track["y1"] + track["y2"]) // 2

        if track_id in track_history:
            prev_cy = track_history[track_id]
            last_time = last_crossing_time.get(track_id, 0)

            if now - last_time > CROSSING_COOLDOWN:
                if prev_cy < line_y <= cy:
                    entry_count += 1
                    last_crossing_time[track_id] = now
                elif prev_cy > line_y >= cy:
                    exit_count += 1
                    last_crossing_time[track_id] = now

        track_history[track_id] = cy


def update_alerts(tracks):
    global active_alerts

    active_alerts = []
    for track in tracks:
        if track.get("suspicious", False):
            active_alerts.append({
                "id": track["id"],
                "dwell_time": track.get("dwell_time", 0),
                "message": f"Person ID {track['id']} — {track.get('dwell_time', 0)}s in monitored zone"
            })


def generate_frames():
    global camera, is_paused, last_frame_bytes, current_person_count, unique_visitor_ids
    global active_concealment_alerts

    while True:
        if camera is None or not camera.isOpened():
            break

        if is_paused:
            if last_frame_bytes is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + last_frame_bytes + b'\r\n')
            time.sleep(0.1)
            continue

        ret, frame = camera.read()

        if not ret:
            break

        height, width = frame.shape[:2]
        line_y = int(height * LINE_Y_RATIO)
        zone_box = get_zone_coordinates(width, height, Settings)

        persons, items = track_all(frame)
        current_person_count = len(persons)

        for p in persons:
            unique_visitor_ids.add(p["id"])

        check_line_crossing(persons, line_y)
        persons = update_zone_tracking(persons, zone_box, Settings.SUSPICIOUS_DWELL_SECONDS)
        update_alerts(persons)

        active_concealment_alerts = update_concealment(persons, items)

        frame = draw_tracks(frame, persons, items, zone_box)

        success, buffer = cv2.imencode('.jpg', frame)

        if not success:
            continue

        last_frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + last_frame_bytes + b'\r\n')