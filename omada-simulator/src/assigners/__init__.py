"""Ticket-assignment strategies for the stage-2 multi-team matrix.

Three strategies plug into the same two-phase contract defined in
``base.py``:

- ``random``   — uniform random dev per ticket
- ``omada``    — call SprintBrain's /api/sprint-brain/plan and apply it
- ``algorithm`` — load-balanced by story points (placeholder, swap-in slot)

The orchestrator picks one per team and calls ``select_tickets`` (which
pops from the shared pool) then ``assign`` (which decides who works what).
"""

from src.assigners.algorithm_assigner import AlgorithmAssigner
from src.assigners.base import (
    AssignmentResult,
    BaseAssigner,
    SprintContext,
    TicketAssignment,
)
from src.assigners.random_assigner import RandomAssigner


_REGISTRY: dict[str, type[BaseAssigner]] = {
    "random": RandomAssigner,
    "algorithm": AlgorithmAssigner,
}


def make_assigner(name: str) -> BaseAssigner:
    """Construct an assigner by short name.

    OmadaAssigner is registered lazily in M2 to avoid pulling the Omada
    observer import into M1's surface area.
    """
    try:
        from src.assigners.omada_assigner import OmadaAssigner
        _REGISTRY.setdefault("omada", OmadaAssigner)
    except ImportError:
        pass

    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown assigner {name!r}. Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


__all__ = [
    "AlgorithmAssigner",
    "AssignmentResult",
    "BaseAssigner",
    "RandomAssigner",
    "SprintContext",
    "TicketAssignment",
    "make_assigner",
]
