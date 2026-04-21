"""Sound effects for Trigonometry Sprint.

Generates short sound effects procedurally so no .wav files are needed.
All sounds are created on init() and cached as pygame.mixer.Sound objects.
"""

import io
import math
import struct
import random

import pygame

from . import prefs
_initialized = False
_sounds = {}
_enabled = True
SAMPLE_RATE = 44100


def _make_wav(samples):
    """Pack a list of float samples (-1..1) into a WAV bytes buffer."""
    buf = io.BytesIO()
    n = len(samples)
    bits = 16
    byte_rate = SAMPLE_RATE * 2
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + n * 2))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, byte_rate, 2, bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", n * 2))
    for s in samples:
        v = max(-1.0, min(1.0, s))
        buf.write(struct.pack("<h", int(v * 30000)))
    buf.seek(0)
    return buf


def _gen_click():
    """Short tick/click — plays on each jump."""
    dur = 0.04
    n = int(SAMPLE_RATE * dur)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = 1.0 - (i / n)
        val = env * env * math.sin(2 * math.pi * 1800 * t) * 0.6
        samples.append(val)
    return _make_wav(samples)


def _gen_orb():
    """Rising chirp — plays when hitting an orb."""
    dur = 0.08
    n = int(SAMPLE_RATE * dur)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = 1.0 - (i / n)
        freq = 600 + 1800 * (i / n)
        val = env * math.sin(2 * math.pi * freq * t) * 0.45
        samples.append(val)
    return _make_wav(samples)


def _gen_death():
    """Low crunch — plays on death."""
    dur = 0.18
    n = int(SAMPLE_RATE * dur)
    rng = random.Random(77)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = max(0.0, 1.0 - (i / n) * 1.2)
        noise = rng.random() * 2 - 1
        sine = math.sin(2 * math.pi * 120 * t)
        val = env * (noise * 0.35 + sine * 0.5)
        samples.append(val)
    return _make_wav(samples)


def _gen_checkpoint():
    """Gentle ascending ding — plays on practice checkpoint."""
    dur = 0.12
    n = int(SAMPLE_RATE * dur)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = max(0.0, 1.0 - (i / n))
        val = env * math.sin(2 * math.pi * 880 * t) * 0.3
        val += env * math.sin(2 * math.pi * 1320 * t) * 0.15
        samples.append(val)
    return _make_wav(samples)


def _gen_win():
    """Rising arpeggio — plays on level complete."""
    dur = 0.3
    n = int(SAMPLE_RATE * dur)
    notes = [523, 659, 784, 1047]
    note_dur = n // len(notes)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        note_idx = min(i // note_dur, len(notes) - 1)
        freq = notes[note_idx]
        local_env = 1.0 - ((i % note_dur) / note_dur) * 0.5
        global_env = 1.0 - (i / n) * 0.3
        val = local_env * global_env * math.sin(2 * math.pi * freq * t) * 0.35
        samples.append(val)
    return _make_wav(samples)


def _gen_pad():
    """Spring boing — plays when hitting a pad."""
    dur = 0.06
    n = int(SAMPLE_RATE * dur)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = 1.0 - (i / n)
        freq = 400 + 600 * env
        val = env * math.sin(2 * math.pi * freq * t) * 0.5
        samples.append(val)
    return _make_wav(samples)


def _gen_gravity():
    """Wobbly flip — plays on gravity flip."""
    dur = 0.07
    n = int(SAMPLE_RATE * dur)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = 1.0 - (i / n)
        freq = 350 - 200 * (i / n)
        val = env * math.sin(2 * math.pi * freq * t) * 0.4
        samples.append(val)
    return _make_wav(samples)


def init():
    """Generate and cache all sound effects."""
    global _initialized, _sounds, _enabled
    if _initialized:
        return
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=512)
    except Exception:
        pass
    _initialized = True
    _enabled = not bool(prefs.get("sfx_muted", False))
    generators = {
        "click": _gen_click,
        "orb": _gen_orb,
        "death": _gen_death,
        "practice_checkpoint": _gen_checkpoint,
        "win": _gen_win,
        "pad": _gen_pad,
        "gravity": _gen_gravity,
    }
    for name, gen in generators.items():
        try:
            wav_buf = gen()
            _sounds[name] = pygame.mixer.Sound(wav_buf)
        except Exception:
            pass


def play(name, volume=0.5):
    """Play a named sound effect.

    The supplied `volume` is treated as a per-sound weight (0..1) and is
    further scaled by the user's master SFX volume from prefs, so adjusting
    the slider in Settings affects every effect immediately.
    """
    if not _enabled or not _initialized:
        return
    snd = _sounds.get(name)
    if snd:
        master = float(prefs.get("sfx_vol", 0.5))
        master = max(0.0, min(1.0, master))
        snd.set_volume(max(0.0, min(1.0, volume)) * master)
        snd.play()


def set_enabled(val):
    """Enable or disable SFX. Persists across sessions."""
    global _enabled
    _enabled = bool(val)
    prefs.set("sfx_muted", not _enabled)


def toggle():
    """Toggle sound effects on/off. Returns new enabled state."""
    set_enabled(not _enabled)
    return _enabled


def toggle_mute():
    """Alias of toggle() for naming symmetry with music.toggle_mute."""
    return toggle()


def is_enabled():
    return _enabled


def is_muted():
    return not _enabled
