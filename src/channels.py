"""Level color-channel table.

Per ``docs/reference/gd_editor_complete_reference.md`` PART 1 §4: "Colors are stored in
numbered 'channels' ... Change a channel's color and every object using
it updates at once." This engine historically set the player's color
directly from a ``PLAYER_COLORS`` palette index (see the old
``col_idx`` field on the Color Trigger); channels replace that direct
index with one level of indirection, following the same sparse-override
philosophy as :mod:`physics`'s ``PhysicsParams`` — a level's
``meta["channels"]`` only needs to list channels that differ from the
default, so a level with no channel table plays identically to one
authored before channels existed.

Wire format (level JSON, inside ``meta``)::

    "channels": {"0": [255, 100, 100, 255], "3": [80, 80, 255, 255]}

Channel ids are arbitrary non-negative integers (bible-inspired cap of
999, not enforced numerically here). An id absent from the level's table
falls back to :data:`DEFAULT_CHANNEL_COLORS` (seeded 1:1 from the
historical ``PLAYER_COLORS`` list so an old Color Trigger's ``col_idx``
means exactly the same thing as the new ``channel`` field), or plain
white if the id is outside that seed range.
"""

from .constants import PLAYER_COLORS

DEFAULT_CHANNEL_COLOR = (255, 255, 255, 255)
DEFAULT_CHANNEL_COLORS = {i: (r, g, b, 255)
                          for i, (r, g, b) in enumerate(PLAYER_COLORS)}


def _coerce_rgba(raw):
    try:
        vals = [int(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if len(vals) == 3:
        vals = vals + [255]
    if len(vals) != 4:
        return None
    return tuple(max(0, min(255, v)) for v in vals)


def channels_from_meta(meta):
    """Level meta -> ``{channel_id: (r, g, b, a)}``. Malformed entries are
    dropped (degrade to defaults) rather than crashing the level load."""
    out = {}
    if not meta:
        return out
    raw = meta.get("channels")
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        try:
            cid = int(key)
        except (TypeError, ValueError):
            continue
        if cid < 0:
            continue
        rgba = _coerce_rgba(val)
        if rgba is not None:
            out[cid] = rgba
    return out


def channel_color(channels, channel_id, fallback=None):
    """Resolve one channel id to an RGBA tuple: explicit level override,
    then the seeded palette default, then plain white."""
    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return fallback or DEFAULT_CHANNEL_COLOR
    if channels and channel_id in channels:
        return channels[channel_id]
    if channel_id in DEFAULT_CHANNEL_COLORS:
        return DEFAULT_CHANNEL_COLORS[channel_id]
    return fallback or DEFAULT_CHANNEL_COLOR


def channels_to_meta_dict(channels):
    """Sparse ``{str(id): [r,g,b,a]}`` of only non-default entries, for
    round-tripping into level JSON without bloating every save."""
    out = {}
    for cid, rgba in (channels or {}).items():
        if DEFAULT_CHANNEL_COLORS.get(cid) != tuple(rgba):
            out[str(cid)] = list(rgba)
    return out
