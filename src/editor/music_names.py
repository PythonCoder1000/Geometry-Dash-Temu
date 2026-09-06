"""Tiny helper: map a level's music filename to its display name."""

from .. import music


def track_label(filename):
    if not filename:
        return "None"
    for t in music.get_tracks():
        if t.get("file") == filename:
            return t.get("name", filename)
    return filename


def next_track(filename):
    """Cycle None -> track 1 -> ... -> None.  Returns ``(file, label)``."""
    tracks = music.get_tracks()
    names = music.get_track_names()
    cur = 0
    if filename is not None:
        for i, t in enumerate(tracks):
            if t.get("file") == filename:
                cur = i + 1
                break
    cur = (cur + 1) % len(names)
    if cur == 0:
        return None, "None"
    return tracks[cur - 1].get("file"), names[cur]
