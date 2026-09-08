"""Runtime compatibility hook.

R1-R3 removed the legacy owner UI monkey-patch chain. Python may import this
module automatically at interpreter startup, so it must remain harmless.
"""

def _install_sabot_owner_hotfix():
    """Deprecated no-op retained only for backwards-compatible imports."""
    return None
