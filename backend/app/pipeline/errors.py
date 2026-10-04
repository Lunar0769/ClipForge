class StageCancelled(Exception):
    """Raised inside a stage when the user cancels the job."""


class StageError(Exception):
    """An expected, user-explainable failure. `hint` tells the user what to do."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
