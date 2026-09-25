"""Domain error hierarchy shared by every control package."""

from __future__ import annotations


class ControlError(Exception):
    """Base class for every recoverable control fault."""

    code = "control-error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"error": self.message, "code": self.code}


class NotFoundError(ControlError):
    code = "not-found"


class WatermarkError(ControlError):
    """Raised when a commit watermark request is out of range."""

    code = "watermark"


class DuplicateRecordError(ControlError):
    """Raised when an append would duplicate a live dedup key."""

    code = "duplicate-record"


class DuplicateBatchError(ControlError):
    """Raised when a batch identifier is reused."""

    code = "duplicate-batch"


class StaleGenerationError(ControlError):
    """Raised when an artifact references a superseded generation."""

    code = "stale-generation"


class ExpiredArtifactError(ControlError):
    """Raised when a confirmation, snapshot or baseline has expired."""

    code = "expired-artifact"


class OutOfOrderError(ControlError):
    """Raised when a stage is entered before its predecessor completed."""

    code = "out-of-order"


class GateBlockedError(ControlError):
    """Raised when a prerequisite gate has not been satisfied."""

    code = "gate-blocked"

    def __init__(self, gate: str, message: str | None = None) -> None:
        super().__init__(message or "gate blocked: " + gate)
        self.gate = gate


class LatchConditionError(ControlError):
    """Raised when a latch transition is refused by its condition."""

    code = "latch-condition"

    def __init__(self, latch: str, action: str, message: str | None = None) -> None:
        super().__init__(message or "latch {} cannot {}".format(latch, action))
        self.latch = latch
        self.action = action


class NotRegisteredError(ControlError):
    code = "not-registered"


class LimitExceededError(ControlError):
    """Raised when a measured value crosses a configured limit."""

    code = "limit-exceeded"

    def __init__(self, subject: str, value: float, limit: float) -> None:
        super().__init__(
            "{} {:.4g} exceeds limit {:.4g}".format(subject, value, limit)
        )
        self.subject = subject
        self.value = value
        self.limit = limit


class NoHeadError(ControlError):
    """A guide operation was attempted without a usable head value."""

    code = "no-head"


class HeadNotPersistedError(ControlError):
    """The head has not been written to durable storage yet."""

    code = "head-not-persisted"


class CoolingClosedError(ControlError):
    """The unit was asked to start with the cooling water shut off."""

    code = "cooling-closed"


class SyncNotConfirmedError(ControlError):
    """Excitation was requested before the synchronizer confirmed."""

    code = "sync-not-confirmed"


class SpeedTooHighError(ControlError):
    """A speed dependent interlock refused the action."""

    code = "speed-too-high"


class GuideLatchedError(ControlError):
    """The guide vane latch is set and blocks the adjustment."""

    code = "guide-latched"


class OverspeedActiveError(ControlError):
    """An overspeed condition blocks the requested operation."""

    code = "overspeed-active"


class RunoutError(ControlError):
    """Vibration runout exceeds the configured limit."""

    code = "runout"


class BrakeLatchedError(ControlError):
    """The brake latch is engaged and blocks the restart."""

    code = "brake-latched"
