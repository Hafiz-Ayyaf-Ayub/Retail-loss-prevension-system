import time

zone_entry_times = {}
suspicious_ids = set()
alert_history = []


def get_zone_coordinates(frame_width, frame_height, settings):
    x1 = int(frame_width * settings.ZONE_X1_RATIO)
    y1 = int(frame_height * settings.ZONE_Y1_RATIO)
    x2 = int(frame_width * settings.ZONE_X2_RATIO)
    y2 = int(frame_height * settings.ZONE_Y2_RATIO)
    return x1, y1, x2, y2


def is_inside_zone(track, zone_box):
    zx1, zy1, zx2, zy2 = zone_box

    cx = (track["x1"] + track["x2"]) // 2
    cy = (track["y1"] + track["y2"]) // 2

    return zx1 <= cx <= zx2 and zy1 <= cy <= zy2


def update_zone_tracking(tracks, zone_box, threshold_seconds):
    global zone_entry_times, suspicious_ids, alert_history

    now = time.time()
    current_ids_in_zone = set()

    for track in tracks:
        track_id = track["id"]

        if is_inside_zone(track, zone_box):
            current_ids_in_zone.add(track_id)

            if track_id not in zone_entry_times:
                zone_entry_times[track_id] = now

            dwell_time = now - zone_entry_times[track_id]
            track["dwell_time"] = round(dwell_time, 1)

            if dwell_time >= threshold_seconds:
                track["suspicious"] = True

                if track_id not in suspicious_ids:
                    suspicious_ids.add(track_id)
                    alert_history.append({
                        "id": track_id,
                        "time": time.strftime("%I:%M:%S %p"),
                        "message": f"ID {track_id} — Wrong Activity Detected"
                    })
            else:
                track["suspicious"] = False
        else:
            track["dwell_time"] = 0
            track["suspicious"] = False

    ids_to_remove = [tid for tid in zone_entry_times if tid not in current_ids_in_zone]
    for tid in ids_to_remove:
        del zone_entry_times[tid]
        suspicious_ids.discard(tid)

    return tracks