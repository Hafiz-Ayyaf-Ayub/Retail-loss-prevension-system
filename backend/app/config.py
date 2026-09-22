class Settings:
    APP_NAME = "Retail Loss Protection System"
    APP_VERSION = "0.1.0"
    CAMERA_SOURCE = 0  # 0 = laptop ka built-in webcam

    # ---- Suspicious Zone Settings (yahan se aasani se adjust karein) ----
    # Zone ek rectangle hai: (x1, y1) top-left corner, (x2, y2) bottom-right corner
    # Values 0.0 se 1.0 ke beech hain — matlab frame ka kitna % hissa
    # Misal: ZONE_X1 = 0.6 matlab zone frame ki chaudai ke 60% se shuru hoga (right side)
    ZONE_X1_RATIO = 0.55
    ZONE_Y1_RATIO = 0.20
    ZONE_X2_RATIO = 0.95
    ZONE_Y2_RATIO = 0.85

    # Kitni der (seconds) tak zone mein rehne par "Wrong Activity" alert banega
    SUSPICIOUS_DWELL_SECONDS = 5