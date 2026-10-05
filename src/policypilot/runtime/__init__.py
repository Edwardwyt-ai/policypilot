"""Application runtime operations used by the tau2 adapter and workflow."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policypilot.runtime.observation import ObservationOutcome


def __getattr__(name: str):
    if name == "ObservationOutcome":
        from policypilot.runtime.observation import ObservationOutcome

        return ObservationOutcome
    raise AttributeError(name)

__all__ = ["ObservationOutcome"]
