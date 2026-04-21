"""Optional gamepad / joystick support.

Wraps `pygame.joystick` so the rest of the game can ask "is the jump button
held?" without caring about hot-plug state, missing controllers, or which
button index maps to A/B/Start on this particular pad.

Usage from the main loop:
    gamepad.init()
    ...
    held = gamepad.jump_held() or keyboard_jump
    pressed_this_frame = gamepad.jump_pressed() or keyboard_pressed

The module never raises if no controller is connected — every accessor is
safe to call regardless. Hot-plug events (`JOYDEVICEADDED` /
`JOYDEVICEREMOVED`) are picked up automatically by `_refresh()` which the
input accessors call lazily.

Default button mapping (works for Xbox-style pads on every platform):
    A button (button 0)        → jump
    B button (button 1)        → back / cancel
    Start button (button 7)    → menu / pause
    Right trigger (axis 5 > 0.5) → also jump (alt fire)

These constants are exposed so a future Settings rebind UI can override
them. For now they're hard-coded — if a controller doesn't match, the
keyboard still works.
"""

import pygame


# Button-index defaults (Xbox layout). Override at runtime if a future
# rebind UI surfaces this.
BTN_JUMP = 0      # A
BTN_BACK = 1      # B
BTN_PAUSE = 7     # Start
TRIGGER_AXIS = 5  # Right trigger (Xbox)
TRIGGER_THRESHOLD = 0.5
DEADZONE = 0.25


_initialized = False
_pad = None
_prev_jump_held = False


def init():
    """Open the first available joystick. Safe to call repeatedly."""
    global _initialized, _pad
    if not _initialized:
        try:
            pygame.joystick.init()
        except pygame.error:
            return
        _initialized = True
    _refresh()


def _refresh():
    """Reattach to a connected pad if our handle went stale."""
    global _pad
    if not _initialized:
        return
    # If our cached pad is still attached, keep it.
    if _pad is not None:
        try:
            _pad.get_init()
            return
        except pygame.error:
            _pad = None
    # Try to attach to joystick 0 if any pads are present.
    try:
        count = pygame.joystick.get_count()
    except pygame.error:
        return
    if count <= 0:
        return
    try:
        js = pygame.joystick.Joystick(0)
        js.init()
        _pad = js
    except pygame.error:
        _pad = None


def is_connected():
    """True if a usable joystick is currently attached."""
    _refresh()
    return _pad is not None


def name():
    """Display name of the attached pad, or '' if none."""
    _refresh()
    if _pad is None:
        return ""
    try:
        return _pad.get_name()
    except pygame.error:
        return ""


def _safe_button(idx):
    if _pad is None:
        return False
    try:
        if idx < 0 or idx >= _pad.get_numbuttons():
            return False
        return bool(_pad.get_button(idx))
    except pygame.error:
        return False


def _safe_axis(idx):
    if _pad is None:
        return 0.0
    try:
        if idx < 0 or idx >= _pad.get_numaxes():
            return 0.0
        return float(_pad.get_axis(idx))
    except pygame.error:
        return 0.0


def jump_held():
    """True while the jump button (or trigger) is held this frame."""
    _refresh()
    if _pad is None:
        return False
    if _safe_button(BTN_JUMP):
        return True
    if _safe_axis(TRIGGER_AXIS) > TRIGGER_THRESHOLD:
        return True
    return False


def jump_pressed():
    """True only on the frame the jump button transitions from up to down.

    Edge-detected so a single tap fires once even though `jump_held()`
    stays True for many frames.
    """
    global _prev_jump_held
    cur = jump_held()
    fired = cur and not _prev_jump_held
    _prev_jump_held = cur
    return fired


def reset_edge_state():
    """Clear edge-detected state — call on scene transitions so a leftover
    button hold doesn't trigger a phantom press in the next loop."""
    global _prev_jump_held
    _prev_jump_held = False
