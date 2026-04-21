"""Baked-in default server URL for built .exe / .app distributions.

When shipped as a standalone binary, players don't get a shell to set
``TRIGSPRINT_SERVER_URL`` in. Edit ``DEFAULT_SERVER_URL`` below to point
the client at the Lightsail (or any) server, then rebuild — every
distributed binary then auto-connects.

Precedence (checked in ``stores.get_stores``):

    1. ``TRIGSPRINT_SERVER_URL`` environment variable (dev / CI override).
    2. ``DEFAULT_SERVER_URL`` below (ships with the build).
    3. Empty / unreachable → fall back to the offline LocalLevelStore.

Leaving this as ``""`` keeps the binary offline-only — useful for
unshared dev builds and tests.
"""

# --- EDIT THIS LINE BEFORE BUILDING FOR DISTRIBUTION -----------------
# Examples:
#   "http://203.0.113.42:8000"           # bare IP, plain HTTP (dev only)
#   "https://play.trigsprint.example"    # domain + TLS (recommended)
DEFAULT_SERVER_URL = "http://35.162.142.94:8000"   
# ---------------------------------------------------------------------
