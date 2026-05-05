# Collects policies for any online access so local-first rules stay explicit and auditable.
# Treat this folder like the mailbox slot: nothing leaves without passing through here first.
# Phase 0 performs no outbound calls; this package simply reserves the decision surface.
# Centralizing network policy prevents accidental credential leaks from helper scripts.

"""Online access policy subpackage for HER."""

from __future__ import annotations

__all__: list[str] = []
