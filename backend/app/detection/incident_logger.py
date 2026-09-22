"""
incident_logger.py

Jab koi concealment "confirm" hoti hai (sustained threshold cross karne ke
baad, concealment_monitor.py se), yeh module 2 kaam karta hai:

  1) Incident ka poora metadata (kaun, kab, kaunsa item, kaunsa camera,
     kaunsi Global ID) ek permanent .jsonl log file mein save karta hai.
  2) Us waqt ke pichle kuch second ke frames (jo camera_stream.py ek
     rolling buffer mein rakhta hai) se ek .mp4 clip bana kar disk pe
     save karta hai — taake security review ke liye asal footage
     mojood rahe.

Dono kaam "best effort" hain: agar video save fail ho jaye (jaise codec
na mile), phir bhi metadata log zaroor ho jata hai (video_path None hoga).
"""

import os
import json
import time
import numpy as np
import cv2

# data/events/ project root ke andar - detection/ folder se 3 level upar
BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "events"
)
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
LOG_PATH = os.path.join(BASE_DIR, "incident_log.jsonl")

os.makedirs(VIDEO_DIR, exist_ok=True)


def save_incident_clip(frame_buffer, incident_id):
    """
    frame_buffer: list of (timestamp, jpg_bytes) tuples, purane->naye order
    (camera_stream.py ki per-camera rolling buffer se aata hai - already
    JPEG-encoded frames, isliye yahan dobara encode nahi karna parta).

    Buffer ke actual timestamps se fps khud nikalta hai (frame-skip/camera
    speed jo bhi ho, clip ki playback speed sahi rahegi).

    Return: saved .mp4 ka path, ya None agar buffer khali/corrupt ho.
    """
    if not frame_buffer or len(frame_buffer) < 2:
        return None

    first_frame = cv2.imdecode(np.frombuffer(frame_buffer[0][1], dtype=np.uint8), cv2.IMREAD_COLOR)
    if first_frame is None:
        return None
    height, width = first_frame.shape[:2]

    duration = frame_buffer[-1][0] - frame_buffer[0][0]
    fps = (len(frame_buffer) - 1) / duration if duration > 0 else 10.0
    fps = max(1.0, min(fps, 30.0))  # sensible range mein rakho

    path = os.path.join(VIDEO_DIR, f"{incident_id}.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))

    if not writer.isOpened():
        return None

    try:
        for _, jpg_bytes in frame_buffer:
            frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)
    finally:
        writer.release()

    return path


def log_incident(metadata: dict):
    """
    metadata dict ko JSONL file mein ek line ke tor par append karta hai
    (har incident apni line - baad mein parse/search karna aasan hota hai).

    Expected keys (camera_stream.py se): camera_id, global_id, person_id,
    item, message, created_at, video_path (ho sakta hai None).
    """
    record = dict(metadata)
    record["logged_at"] = time.strftime("%Y-%m-%d %I:%M:%S %p")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[incident_logger] Warning: log likhne mein masla: {e}")