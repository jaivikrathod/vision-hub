"""Shared helpers for activity models: sliding windows, smoothing and segments.

Windows are dicts ``{"track_id", "start", "end", "scores": {label: p}, "label", "confidence"}``
on one track, in time order. Times are seconds.
"""

from __future__ import annotations

from collections import Counter

UNCERTAIN = "uncertain"


def window_starts(first: float, last: float, window: float, stride: float) -> list[float]:
    """Start times of fixed-length windows covering ``[first, last]``.

    A track shorter than one window gets a single window over its whole span.
    """
    span = last - first
    if span <= window:
        return [first]
    n = int((span - window) // stride) + 1
    starts = [first + i * stride for i in range(n)]
    if starts[-1] + window < last - stride / 2:
        starts.append(last - window)  # cover the tail
    return starts


def pick_label(scores: dict[str, float], threshold: float) -> tuple[str, float]:
    if not scores:
        return UNCERTAIN, 0.0
    label, score = max(scores.items(), key=lambda kv: kv[1])
    return (label, score) if score >= threshold else (UNCERTAIN, score)


def smooth_labels(windows: list[dict], k: int) -> list[str]:
    """Majority filter over ``k`` neighbouring windows (odd ``k``; 1 = no smoothing).

    Removes one-window flickers; a tie keeps the window's own label.
    """
    labels = [w["label"] for w in windows]
    if k <= 1 or len(labels) < 3:
        return labels
    half = k // 2
    out = []
    for i, own in enumerate(labels):
        neigh = labels[max(0, i - half): i + half + 1]
        (best, n), *rest = Counter(neigh).most_common()
        out.append(best if n > len(neigh) / 2 and (not rest or rest[0][1] < n) else own)
    return out


def windows_to_segments(windows: list[dict], labels: list[str], stride: float, method: str) -> list[dict]:
    """Tile the timeline with the windows and merge equal consecutive labels.

    Neighbouring windows that overlap or nearly touch split the time between them
    at the midpoint of their centres, so segments are contiguous. Where the person
    was not visible (a gap longer than one stride), the segment ends at the window's
    own end. Segment confidence is the mean score of the segment's label over its windows.
    """
    if not windows:
        return []
    segments: list[dict] = []
    n = len(windows)
    centres = [(w["start"] + w["end"]) / 2 for w in windows]

    def joined(i: int) -> bool:  # window i and i+1 overlap or are at most one stride apart
        return windows[i + 1]["start"] - windows[i]["end"] <= stride

    for i, (w, label) in enumerate(zip(windows, labels)):
        start = (centres[i - 1] + centres[i]) / 2 if i > 0 and joined(i - 1) else w["start"]
        end = (centres[i] + centres[i + 1]) / 2 if i < n - 1 and joined(i) else w["end"]
        if end <= start:
            continue
        score = w["scores"].get(label, w["confidence"]) if label != UNCERTAIN else w["confidence"]
        last = segments[-1] if segments else None
        # Contiguous (ends are stored rounded to ms, so compare with a small tolerance) and same label.
        if last and last["label"] == label and start - last["end"] <= 0.002:
            last["end"] = round(end, 3)
            last["_scores"].append(score)
        else:
            segments.append({"track_id": w["track_id"], "start": round(start, 3), "end": round(end, 3),
                             "label": label, "method": method, "_scores": [score]})
    for s in segments:
        scores = s.pop("_scores")
        s["confidence"] = round(sum(scores) / len(scores), 3)
    return segments
