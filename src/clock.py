from time import monotonic
from typing import Callable, Optional

LAMBDA_CEILING_SECONDS = 900.0


def deadline_clock(context: Optional[object]) -> Callable[[], float]:
    lambda_clock = getattr(context, 'get_remaining_time_in_millis', None)
    if lambda_clock is not None:
        return lambda: float(lambda_clock()) / 1000.0
    started = monotonic()
    return lambda: LAMBDA_CEILING_SECONDS - (monotonic() - started)
