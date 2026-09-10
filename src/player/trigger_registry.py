"""Trigger dispatch table + same-frame activation-ordering constants.

``TRIGGER_HANDLERS`` maps an object type (the ``"t"`` key) to the unbound
``TriggerMixin`` method that runs that trigger's effect. It is one flat
module-level dict, populated by ``triggers.py`` at import time (see the
registration block at the bottom of that module) rather than by a
decorator or a per-family module: a single table stays greppable and
auditable as the trigger roster grows, and mirrors how ``TRIGGER_TYPES``/
``CONTROL_TRIGGER_TYPES`` are already flat frozensets in ``constants.py``.

Handlers are stored unbound and invoked as ``handler(player, obj)``.
"""

TRIGGER_HANDLERS = {}

# Activation-family ranks -- the first element of a queued trigger event's
# sort key (see TriggerMixin._enqueue_trigger_event).
#
# deep-research-report.md ("Same-frame precedence") specifies ordering
# *within* the spawn family (left-to-right by x) and an ascending Trigger
# Order for regular/touch triggers, but does NOT specify how the families
# rank against each other. These ranks are therefore an explicit engine
# convention, not a documented GD rule: spawn-chain activations resolve
# before player-touch activations, which resolve before the (currently
# unused) "regular"/line-activated family, so a chain fired earlier in the
# tick has finished mutating state before a touch in the same tick reads it.
TRIGGER_FAMILY_SPAWN = 0
TRIGGER_FAMILY_TOUCH = 1
TRIGGER_FAMILY_REGULAR = 2

# A handler may enqueue further events (Spawn firing a group, Item Comp
# firing on a comparison, ...), so the drain loop re-runs until the queue
# is empty. This bounds a level that builds a self-refiring trigger cycle:
# after this many passes the tick's queue is dropped instead of hanging the
# simulation, consistent with the existing defensive handling of the
# previously-fixed self-refire bug (docs/development/AUDIT.md Sec 12).
TRIGGER_DRAIN_MAX_PASSES = 64
