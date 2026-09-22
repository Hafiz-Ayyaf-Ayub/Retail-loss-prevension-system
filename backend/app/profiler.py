"""
profiler.py  -  "System slow kyun hai?" ka jawab naapne wala chhota helper.

Kaam: har camera ke har hisse (camera read, YOLO, Re-ID, pose, concealment,
drawing, JPEG encode) ka average waqt naapta hai, aur har PRINT_EVERY_SECONDS
baad terminal mein ek line chhapta hai. Isse pata chalta hai ke sab se
zyada waqt KAUNSA hissa kha raha hai - andaze se optimize karne ki jagah
pehle naapo, phir sirf sab se bhaari hisse ko theek karo.

Band karna ho to PROFILING_ENABLED = False kar do.
"""

import time

PROFILING_ENABLED = True
PRINT_EVERY_SECONDS = 5

# cam_id -> {"stages": {name: [total_seconds, calls]}, "frames": n, "since": t}
_data = {}


def _cam(cam_id):
    if cam_id not in _data:
        _data[cam_id] = {"stages": {}, "frames": 0, "since": time.time()}
    return _data[cam_id]


class stage:
    """Istemal:  with profiler.stage(cam_id, "yolo"):  <kaam>"""

    def __init__(self, cam_id, name):
        self.cam_id = cam_id
        self.name = name

    def __enter__(self):
        if PROFILING_ENABLED:
            self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        if PROFILING_ENABLED:
            elapsed = time.perf_counter() - self.t0
            entry = _cam(self.cam_id)["stages"].setdefault(self.name, [0.0, 0])
            entry[0] += elapsed
            entry[1] += 1
        return False


def frame_done(cam_id):
    """Har frame ke aakhir mein bulao - FPS ginta hai aur waqt par report chhapta hai."""
    if not PROFILING_ENABLED:
        return

    data = _cam(cam_id)
    data["frames"] += 1

    now = time.time()
    elapsed = now - data["since"]
    if elapsed < PRINT_EVERY_SECONDS:
        return

    fps = data["frames"] / elapsed
    parts = []
    for name, (total, calls) in data["stages"].items():
        avg_ms = (total / calls) * 1000 if calls else 0
        parts.append(f"{name} {avg_ms:.0f}ms(x{calls})")

    print(f"[PROFILE cam{cam_id}] FPS={fps:.1f} | " + " | ".join(parts))

    data["stages"] = {}
    data["frames"] = 0
    data["since"] = now