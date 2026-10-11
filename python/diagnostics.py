"""Pool of checks: turns each Cell's ratio history into a verdict. No arduino.* imports."""

HEALTHY_RATIO = 0.9
LOW_RATIO = 0.6
SUDDEN_DROP = 0.25
PERSIST_MIN_SAMPLES = 5
VARIANCE_MIN = 0.15
TREND_MIN_SAMPLES = 4  # below this, there's not enough history to call fast vs gradual
TREND_MIN_DROP = 0.1


def _is_healthy(cell):
    return cell.last_ratio is not None and cell.last_ratio >= HEALTHY_RATIO


def _is_low(cell):
    return cell.last_ratio is not None and cell.last_ratio <= LOW_RATIO


SUDDEN_WINDOW = 3  # samples; a drop counts as "sudden" only within this recent a span


def _dropped_fast(cell):
    ratios = cell.recent_ratios()
    if len(ratios) < 2 or cell.last_ratio is None:
        return False
    recent = ratios[-SUDDEN_WINDOW:]
    return (max(recent) - cell.last_ratio) >= SUDDEN_DROP


def _declining(cell):
    """True only if the ratio history actually trends down -- not just 'low
    the whole time', which is a different, unknown-cause situation."""
    ratios = cell.recent_ratios()
    if len(ratios) < TREND_MIN_SAMPLES:
        return False
    half = len(ratios) // 2
    first_avg = sum(ratios[:half]) / half
    second_avg = sum(ratios[half:]) / (len(ratios) - half)
    return (first_avg - second_avg) >= TREND_MIN_DROP


def _variance(cell):
    ratios = cell.recent_ratios()
    return (max(ratios) - min(ratios)) if ratios else 0.0


def analyze(cells, t=None):
    """Run the pool of checks over every cell and update each one's status."""
    if not cells:
        return

    if all(_is_healthy(c) for c in cells):
        for c in cells:
            c.set_status("healthy", "at or above baseline", 0.5, t)
        return

    low = [c for c in cells if _is_low(c)]
    healthy = [c for c in cells if _is_healthy(c)]

    if len(low) == 1 and healthy:
        lo = low[0]
        if _dropped_fast(lo):
            lo.set_status(
                "obstacle",
                f"ratio dropped to {lo.last_ratio:.2f} suddenly, others normal",
                0.9, t)
        elif _declining(lo):
            others_vary = any(
                _variance(c) > VARIANCE_MIN for c in cells if c is not lo)
            if others_vary:
                lo.set_status(
                    "defect",
                    f"stuck at {lo.last_ratio:.2f} while other cells vary",
                    0.8, t)
            else:
                lo.set_status("dirt",
                              f"ratio down to {lo.last_ratio:.2f}, gradual",
                              0.75, t)
        else:
            lo.set_status(
                "shaded",
                f"ratio at {lo.last_ratio:.2f}, not enough history to tell cause",
                0.4, t)
        for c in healthy:
            c.set_status("healthy", "at or above baseline", 0.5, t)
        return

    if len(cells) > 1 and len(low) == len(cells):
        if any(_dropped_fast(c) for c in cells):
            label, reason, confidence = "cloud", "all cells dropped together, suddenly", 0.7
        elif any(_declining(c) for c in cells):
            label, reason, confidence = "dust", "all cells declined together, gradually", 0.6
        else:
            label, reason, confidence = "shaded", "all cells low together, not enough history to tell cause", 0.4
        for c in cells:
            c.set_status(label, reason, confidence, t)
        return

    for c in cells:
        if c.last_ratio is not None and not _is_healthy(c) and not _is_low(c):
            c.set_status("unknown", f"ratio {c.last_ratio:.2f}, inconclusive",
                         0.3, t)
