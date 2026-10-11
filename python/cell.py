"""Per-cell diagnostic state. No arduino.* imports."""
import time
from collections import deque

BASELINE_DECAY = 0.98  # per update(); slow, same idea as the LED matrix's auto-ranging peak
HISTORY_LEN = 20
MAX_EVENTS = 50


class Cell:
    def __init__(self, index, cell_id):
        self.index = index
        self.id = cell_id
        self.baseline = 1.0
        self.ratio_history = deque(maxlen=HISTORY_LEN)  # (t, ratio)
        self.last_ma = None
        self.last_ratio = None
        self.status = "unknown"
        self.status_reason = ""
        self.status_confidence = 0.0
        self.status_since = None
        self.events = []       # closed status spans
        self.open_event = None  # current span, mirrors status/status_reason/status_confidence

    def update(self, ma, t=None):
        t = t if t is not None else time.time()
        self.baseline = max(ma, self.baseline) if ma > self.baseline else self.baseline * BASELINE_DECAY
        self.baseline = max(self.baseline, 1.0)
        self.last_ma = ma
        self.last_ratio = ma / self.baseline
        self.ratio_history.append((t, self.last_ratio))

    def recent_ratios(self):
        return [r for _, r in self.ratio_history]

    def set_status(self, label, reason, confidence, t=None):
        t = t if t is not None else time.time()
        if self.open_event and self.open_event["label"] == label:
            self.open_event["active_s"] = round(t - self.open_event["started_at"], 1)
            self.open_event["reason"] = reason
            self.open_event["confidence"] = confidence
        else:
            if self.open_event:
                self.open_event["ended_at"] = t
                self.events.append(self.open_event)
                self.events = self.events[-MAX_EVENTS:]
            self.open_event = {
                "label": label,
                "reason": reason,
                "confidence": confidence,
                "started_at": t,
                "ended_at": None,
                "active_s": 0.0,
                "ma_at_start": self.last_ma,
            }
            self.status_since = t
        self.status = label
        self.status_reason = reason
        self.status_confidence = confidence

    def to_persist(self):
        return {
            "baseline": self.baseline,
            "status": self.status,
            "status_reason": self.status_reason,
            "status_confidence": self.status_confidence,
            "status_since": self.status_since,
            "open_event": self.open_event,
            "events": self.events,
        }

    def load_persisted(self, data):
        self.baseline = data.get("baseline", self.baseline)
        self.status = data.get("status", self.status)
        self.status_reason = data.get("status_reason", self.status_reason)
        self.status_confidence = data.get("status_confidence", self.status_confidence)
        self.status_since = data.get("status_since", self.status_since)
        self.open_event = data.get("open_event", self.open_event)
        self.events = data.get("events", self.events)

    def to_dict(self):
        return {
            "index": self.index,
            "id": self.id,
            "baseline": round(self.baseline, 2),
            "last_ma": self.last_ma,
            "last_ratio": round(self.last_ratio, 3) if self.last_ratio is not None else None,
            "status": self.status,
            "status_reason": self.status_reason,
            "status_confidence": round(self.status_confidence, 2),
            "status_since": self.status_since,
            "open_event": self.open_event,
            "events": self.events[-10:],
        }
