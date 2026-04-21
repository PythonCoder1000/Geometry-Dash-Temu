"""Music system for Trigonometry Sprint.

Supports:
- Loading .ogg/.mp3/.wav files from assets/music/
- Procedurally generated chiptune tracks as fallback
- Per-level music assignment (stored as filename in level JSON)
- Volume control and track switching
- Togglable on/off
"""

import os
import math
import struct
import random
import shutil

import pygame

from constants import ASSETS_DIR, USER_MUSIC_DIR
import prefs

MUSIC_DIR = os.path.join(ASSETS_DIR, "music")  # Read-only (bundled)
_initialized = False
_current_track = None
_volume = 0.5
_tracks = []
_enabled = True
_menu_track_index = 0  # Which track plays on the menu (index into _tracks)


def init():
    """Initialize the music system and scan for music files."""
    global _initialized, _tracks, _enabled, _volume, _menu_track_index
    if _initialized:
        return
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
    except Exception:
        pass
    _initialized = True
    _tracks = scan_tracks()
    # Restore persisted preferences.
    # Music defaults to OFF on first launch — the user opts in via the
    # Music menu. Previously this was opt-out which surprised players who
    # just wanted to boot the game without audio.
    _enabled = not bool(prefs.get("music_muted", True))
    _volume = float(prefs.get("music_vol", 0.5))
    _menu_track_index = int(prefs.get("menu_track", 0))
    if _menu_track_index < 0 or _menu_track_index >= len(_tracks):
        _menu_track_index = 0
    set_volume(_volume)


def scan_tracks():
    """Scan bundled + user music dirs for playable tracks."""
    tracks = []
    seen_files = set()
    # Order matters — user-imported tracks come first so they surface at
    # the top of the picker (most recently added is the one users want).
    for base in (USER_MUSIC_DIR, MUSIC_DIR):
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            continue
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if not f.lower().endswith((".ogg", ".mp3", ".wav")):
                continue
            if f in seen_files:
                continue  # dupe name across dirs — prefer user copy
            seen_files.add(f)
            tracks.append({
                "name": os.path.splitext(f)[0].replace("_", " ").title(),
                "file": f,
                "path": os.path.join(base, f),
                "type": "file",
            })
    # Always add generated tracks as fallback.
    tracks.append({"name": "Chiptune A", "file": "__chiptune_a", "type": "generated", "seed": 42})
    tracks.append({"name": "Chiptune B", "file": "__chiptune_b", "type": "generated", "seed": 99})
    tracks.append({"name": "Chiptune C", "file": "__chiptune_c", "type": "generated", "seed": 7})
    return tracks


def rescan():
    """Re-scan music directory (call after importing a file)."""
    global _tracks
    _tracks = scan_tracks()


def get_tracks():
    """Return list of available track dicts."""
    if not _initialized:
        init()
    return list(_tracks)


def get_track_names():
    """Return list of track display names, with 'None' at index 0."""
    if not _initialized:
        init()
    return ["None"] + [t["name"] for t in _tracks]


def track_index_by_file(filename):
    """Find track index by filename. Returns None if not found."""
    if not filename:
        return None
    for i, t in enumerate(_tracks):
        if t.get("file") == filename:
            return i
    return None


def import_music_file(src_path):
    """Copy a music file into USER_MUSIC_DIR and rescan. Returns the
    basename so the level JSON / menu can reference it."""
    try:
        os.makedirs(USER_MUSIC_DIR, exist_ok=True)
    except OSError:
        return None
    basename = os.path.basename(src_path)
    if not basename.lower().endswith((".ogg", ".mp3", ".wav")):
        return None
    dest = os.path.join(USER_MUSIC_DIR, basename)
    if os.path.abspath(src_path) != os.path.abspath(dest):
        try:
            shutil.copy2(src_path, dest)
        except (OSError, shutil.SameFileError):
            return None
    rescan()
    return basename


def pick_music_file_dialog(parent_title="Import music"):
    """Open a native file-picker dialog and return the selected path, or
    None if the user cancelled / no GUI is available.

    Dispatch by platform:
    - **macOS**: use ``osascript``'s ``choose file`` because tkinter in
      the same process as pygame crashes — pygame's SDL replaces
      ``NSApplication`` with ``SDLApplication``, which Tk's
      ``[app macOSVersion]`` call blows up on.
    - **Windows / Linux**: spawn a short Python subprocess that runs
      tkinter. Isolating Tk in its own process also avoids subtle
      interactions on other platforms (Tk can leave `Quit` menu items
      registered on the main NSApp / hijack focus).
    """
    import sys as _sys
    if _sys.platform == "darwin":
        return _pick_file_osascript(parent_title)
    return _pick_file_tk_subprocess(parent_title)


def _pick_file_osascript(title):
    """macOS native file picker via osascript — avoids the SDL/Tk
    NSApplication conflict that crashes pygame apps."""
    import subprocess
    script = (
        'set chosen to choose file with prompt "{title}" '
        'of type {{"mp3","MP3","wav","WAV","ogg","OGG"}}\n'
        'return POSIX path of chosen'
    ).format(title=title.replace('"', "'"))
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # User cancel → returncode != 0 and a specific stderr message.
    if out.returncode != 0:
        return None
    path = out.stdout.strip()
    return path or None


def _pick_file_tk_subprocess(title):
    """tkinter in a subprocess — safe on Windows/Linux. Returns the
    picked path or None."""
    import subprocess
    import sys as _sys
    script = (
        "import tkinter, tkinter.filedialog as fd\n"
        "r = tkinter.Tk()\n"
        "r.withdraw()\n"
        "try:\n"
        "    r.attributes('-topmost', True)\n"
        "except Exception:\n"
        "    pass\n"
        "p = fd.askopenfilename(title=" + repr(title) + ", filetypes=[\n"
        "    ('Audio', '*.mp3 *.ogg *.wav'),\n"
        "    ('MP3', '*.mp3'), ('OGG', '*.ogg'), ('WAV', '*.wav'),\n"
        "    ('All files', '*.*'),\n"
        "])\n"
        "print(p or '')\n"
    )
    try:
        out = subprocess.run(
            [_sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    path = out.stdout.strip()
    return path or None


def set_volume(vol):
    """Set music volume (0.0 to 1.0)."""
    global _volume
    _volume = max(0.0, min(1.0, vol))
    prefs.set("music_vol", _volume)
    try:
        pygame.mixer.music.set_volume(_volume)
    except Exception:
        pass


def get_volume():
    return _volume


def set_enabled(val):
    """Enable or disable music entirely. Persists across sessions."""
    global _enabled
    _enabled = bool(val)
    prefs.set("music_muted", not _enabled)
    if not _enabled:
        stop()


def is_enabled():
    return _enabled


def toggle_mute():
    """Toggle music mute. Returns new enabled state."""
    set_enabled(not _enabled)
    if _enabled:
        play_menu_music()
    return _enabled


def is_muted():
    return not _enabled


def play_track(index=0, loops=-1, start_sec=0.0):
    """Play a track by index. loops=-1 means loop forever. ``start_sec``
    seeks into the track before playback — only supported on file
    tracks; generated chiptunes ignore the offset."""
    global _current_track
    if not _initialized:
        init()
    if not _enabled:
        return
    if not _tracks or index < 0 or index >= len(_tracks):
        return
    track = _tracks[index]
    _current_track = index
    try:
        if track["type"] == "file":
            pygame.mixer.music.load(track["path"])
            pygame.mixer.music.set_volume(_volume)
            if start_sec and start_sec > 0.0:
                try:
                    pygame.mixer.music.play(loops, start=float(start_sec))
                except (pygame.error, TypeError):
                    # Some formats / platforms refuse `start` — fall back
                    # to playing from 0 rather than going silent.
                    pygame.mixer.music.play(loops)
            else:
                pygame.mixer.music.play(loops)
        elif track["type"] == "generated":
            _play_generated(track["seed"], loops)
    except Exception:
        pass


def play_file(filename, loops=-1, start_sec=0.0):
    """Play a track by its filename. Returns True if found and started.
    ``start_sec`` seeks into the file (playtest-from-cursor uses this to
    keep the music in sync with the level position)."""
    if not filename or not _enabled:
        return False
    idx = track_index_by_file(filename)
    if idx is not None:
        play_track(idx, loops, start_sec=start_sec)
        return True
    # Try direct path in the bundled or user music dir.
    path = None
    for base in (USER_MUSIC_DIR, MUSIC_DIR):
        candidate = os.path.join(base, filename)
        if os.path.exists(candidate):
            path = candidate
            break
    if path is not None:
        global _current_track
        _current_track = None
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(_volume)
            if start_sec and start_sec > 0.0:
                try:
                    pygame.mixer.music.play(loops, start=float(start_sec))
                except (pygame.error, TypeError):
                    pygame.mixer.music.play(loops)
            else:
                pygame.mixer.music.play(loops)
            return True
        except Exception:
            return False
    return False


def _play_generated(seed, loops=-1):
    """Generate and play a simple chiptune track using raw audio."""
    try:
        rng = random.Random(seed)
        sample_rate = 44100
        bpm = rng.choice([120, 130, 140, 150, 160])
        beat_len = int(sample_rate * 60 / bpm)

        base_notes = [262, 294, 330, 392, 440, 524, 588, 660, 784, 880]
        num_beats = 32
        melody = []
        for i in range(num_beats):
            if rng.random() < 0.15:
                melody.append(0)
            else:
                melody.append(rng.choice(base_notes))

        bass_notes = [131, 147, 165, 196, 220]
        bass = []
        for i in range(num_beats // 2):
            bass.append(rng.choice(bass_notes))

        total_samples = beat_len * num_beats
        samples = []

        for s in range(total_samples):
            beat_idx = s // beat_len
            t = s / sample_rate
            mel_val = 0.0
            note_freq = melody[beat_idx % len(melody)]
            if note_freq > 0:
                beat_pos = (s % beat_len) / beat_len
                env = min(1.0, beat_pos * 20) * max(0.0, 1.0 - beat_pos * 1.5)
                phase = (t * note_freq) % 1.0
                mel_val = (0.3 if phase < 0.5 else -0.3) * env
            bass_idx = (beat_idx // 2) % len(bass)
            bass_freq = bass[bass_idx]
            bass_phase = (t * bass_freq) % 1.0
            bass_val = (abs(bass_phase * 4 - 2) - 1) * 0.2
            kick_pos = (s % beat_len) / beat_len
            kick_val = 0.0
            if kick_pos < 0.08:
                kick_freq = 150 * (1.0 - kick_pos / 0.08)
                kick_val = math.sin(2 * math.pi * kick_freq * kick_pos) * 0.4 * (1.0 - kick_pos / 0.08)
            hat_val = 0.0
            half_beat = beat_len // 2
            hat_pos_in_half = (s % half_beat) / half_beat
            if hat_pos_in_half < 0.03:
                hat_val = (rng.random() * 2 - 1) * 0.1 * (1.0 - hat_pos_in_half / 0.03)
            val = mel_val + bass_val + kick_val + hat_val
            val = max(-1.0, min(1.0, val))
            samples.append(int(val * 28000))

        import io
        buf = io.BytesIO()
        num_channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = len(samples) * block_align
        buf.write(b'RIFF')
        buf.write(struct.pack('<I', 36 + data_size))
        buf.write(b'WAVE')
        buf.write(b'fmt ')
        buf.write(struct.pack('<IHHIIHH', 16, 1, num_channels, sample_rate,
                              byte_rate, block_align, bits_per_sample))
        buf.write(b'data')
        buf.write(struct.pack('<I', data_size))
        for s in samples:
            buf.write(struct.pack('<h', max(-32768, min(32767, s))))
        buf.seek(0)
        pygame.mixer.music.load(buf, "wav")
        pygame.mixer.music.set_volume(_volume)
        pygame.mixer.music.play(loops)
    except Exception:
        pass


def fadeout(ms=1000):
    """Fade out music over *ms* milliseconds, then stop."""
    try:
        pygame.mixer.music.fadeout(ms)
    except Exception:
        pass


def stop():
    """Stop music playback."""
    global _current_track
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    _current_track = None


def pause():
    """Pause music playback."""
    try:
        pygame.mixer.music.pause()
    except Exception:
        pass


def unpause():
    """Resume music playback."""
    try:
        pygame.mixer.music.unpause()
    except Exception:
        pass


def is_playing():
    """Check if music is currently playing."""
    try:
        return pygame.mixer.music.get_busy()
    except Exception:
        return False


def current_track_index():
    """Get the index of the currently playing track."""
    return _current_track


def current_track_file():
    """Get the filename of the currently playing track, or None."""
    if _current_track is not None and 0 <= _current_track < len(_tracks):
        return _tracks[_current_track].get("file")
    return None


def next_track():
    """Switch to the next track."""
    if not _tracks:
        return
    idx = (_current_track or 0) + 1
    if idx >= len(_tracks):
        idx = 0
    play_track(idx)


def prev_track():
    """Switch to the previous track."""
    if not _tracks:
        return
    idx = (_current_track or 0) - 1
    if idx < 0:
        idx = len(_tracks) - 1
    play_track(idx)


def get_menu_track_index():
    """Get the index of the menu music track."""
    return _menu_track_index


def set_menu_track_index(idx):
    """Set which track plays on the menu."""
    global _menu_track_index
    if _tracks and 0 <= idx < len(_tracks):
        _menu_track_index = idx
        prefs.set("menu_track", idx)


def play_menu_music():
    """Play the configured menu music track."""
    if not _enabled or not _tracks:
        return
    play_track(_menu_track_index)


def next_menu_track():
    """Cycle to the next menu track and start playing it."""
    global _menu_track_index
    if not _tracks:
        return
    _menu_track_index = (_menu_track_index + 1) % len(_tracks)
    prefs.set("menu_track", _menu_track_index)
    if _enabled:
        play_track(_menu_track_index)


def prev_menu_track():
    """Cycle to the previous menu track and start playing it."""
    global _menu_track_index
    if not _tracks:
        return
    _menu_track_index = (_menu_track_index - 1) % len(_tracks)
    prefs.set("menu_track", _menu_track_index)
    if _enabled:
        play_track(_menu_track_index)
