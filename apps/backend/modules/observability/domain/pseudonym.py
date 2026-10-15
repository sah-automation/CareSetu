"""MOD-013: pseudonymous actor keys for the observability schema (B6 #723).

Attribution needs to say "this spend belongs to that patient" without storing
who the patient is. The observability schema is PHI-free by rule
(``ADR-0025`` D7; ``error-handling-observability.md`` §5 - "pseudonymous ids
only"), so an identity reference that arrives on an event is hashed on the way
in rather than written down: the daily aggregate can group spend per actor and
the rollup can join a doctor edge back to a spend row, but neither the row nor a
backup of it names a person.

The hash is one-way and domain-separated. The domain separator is not decoration:
patient references and doctor references are drawn from different id spaces and
may collide numerically, so hashing the kind into the preimage is what stops a
patient ``7`` and a doctor ``7`` sharing one key in an aggregate keyed on
``(actor_kind, actor_key)``.

Pure and deterministic by construction - no clock, no settings, no I/O - so the
same reference always produces the same key and a key computed at consume time
joins a key computed at rollup time. That determinism is the reason this is a
plain digest rather than a per-deployment secret: attribution is a grouping
operation, not an authentication one, and a secret that rotated would silently
break every historical join.

What this is not: a defence against someone who already holds the rows. The
references are dense database serials, so the preimage space is small and the
digest is enumerable by anyone who knows this module's construction. The control
here is that the identity column of the telemetry store is not the identity
itself - ``intake_ai_jobs`` and ``intake_intakes`` remain the only places the
raw reference is written, and they stay behind the clinical boundary. A
deployment-keyed hash is a configuration change (a new secret plus a re-hash of
every row written so far), not a change to this function's signature, so it stays
possible - but it is not free, and it belongs with the config gates rather than
smuggled in beside them.
"""

from __future__ import annotations

import hashlib
from typing import Literal

#: The actor kinds a key may be minted for. These are the closed vocabulary of
#: ``observability_attribution_daily.actor_kind`` - the two halves of the
#: per-patient / per-doctor attribution the business reads are built on. Typed as
#: a ``Literal`` rather than left as ``str`` so a misspelled kind is a type error
#: at the call site, not a CHECK-constraint violation raised from the database
#: halfway through a consumer transaction.
ActorKind = Literal["patient", "doctor"]
ACTOR_KIND_PATIENT: ActorKind = "patient"
ACTOR_KIND_DOCTOR: ActorKind = "doctor"

#: Domain separator mixed into every preimage, so a key minted here can never
#: collide with a digest produced for some other purpose in the same codebase.
_ACTOR_DOMAIN = "caresetu.observability.actor.v1"


def actor_key(actor_kind: ActorKind, actor_ref: int) -> str:
    """Return the one-way pseudonymous key for ``actor_ref`` within ``actor_kind``.

    ``actor_kind`` is part of the hashed preimage (see the module docstring), so
    the same reference in two kinds yields two unrelated keys. The reference
    itself is never returned, logged, or stored anywhere by this module.
    """
    preimage = f"{_ACTOR_DOMAIN}:{actor_kind}:{actor_ref}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()
