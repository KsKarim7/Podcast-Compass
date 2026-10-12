"""Caps on how much of the free tier this demo can spend.

Two separate guards, for two different problems:

* a per-session cap and a minimum gap between actions, which stop one visitor from
  using the whole day's allowance;
* a process-wide daily cap counted in *requests*, which keeps the total inside the
  free tier even though one user action can cost up to three requests.

Counting requests rather than actions is the point. A generation is one request, two
if the fallback model is used, three if a repair retry is also needed. Capping actions
at 400 could therefore spend 1,200 requests; capping requests cannot overshoot.

Nothing here imports streamlit. The clock is injectable so the tests do not sleep.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

from . import config, messages

# One action can cost: the first call, a fallback call, and a repair retry.
REQUESTS_PER_ACTION = 3

MAX_SESSION_ACTIONS = 10
MAX_DAILY_REQUESTS = 400
MIN_SECONDS_BETWEEN_ACTIONS = 4.0



def _utc_today(now: Callable[[], datetime]) -> date:
    return now().astimezone(timezone.utc).date()


@dataclass
class SessionUsage:
    """Per-browser-session state. Lives in st.session_state in the running app."""

    actions: int = 0
    last_action_at: float | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    message: str = ""


class DailyCounter:
    """Process-wide request count for the current UTC day.

    Reserve before a call and settle afterwards with what was actually spent, so a
    worst-case action can never take the total past the limit even if several sessions
    start at once.
    """

    def __init__(
        self,
        limit: int = MAX_DAILY_REQUESTS,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._limit = limit
        self._now = now
        self._lock = threading.Lock()
        self._day = _utc_today(now)
        self._used = 0

    @property
    def limit(self) -> int:
        return self._limit

    def _roll_day_if_needed(self) -> None:
        today = _utc_today(self._now)
        if today != self._day:
            self._day = today
            self._used = 0

    def used(self) -> int:
        with self._lock:
            self._roll_day_if_needed()
            return self._used

    def remaining(self) -> int:
        with self._lock:
            self._roll_day_if_needed()
            return max(0, self._limit - self._used)

    def reserve(self, cost: int = REQUESTS_PER_ACTION) -> bool:
        """Take `cost` requests from the day's budget, or refuse if they are not there."""
        with self._lock:
            self._roll_day_if_needed()
            if self._used + cost > self._limit:
                return False
            self._used += cost
            return True

    def settle(self, reserved: int, actual: int) -> None:
        """Give back whatever the action did not use."""
        with self._lock:
            self._roll_day_if_needed()
            refund = max(0, reserved - actual)
            self._used = max(0, self._used - refund)

    def release(self, reserved: int) -> None:
        """Give it all back, for an action that never reached the provider."""
        self.settle(reserved, 0)


def check(
    session: SessionUsage,
    daily: DailyCounter,
    *,
    monotonic: float,
    cost: int = REQUESTS_PER_ACTION,
) -> Decision:
    """Would another action be allowed? Checked before anything is reserved."""
    if session.actions >= MAX_SESSION_ACTIONS:
        return Decision(False, messages.SESSION_CAP.format(limit=MAX_SESSION_ACTIONS))

    if session.last_action_at is not None:
        waited = monotonic - session.last_action_at
        if waited < MIN_SECONDS_BETWEEN_ACTIONS:
            return Decision(False, messages.TOO_SOON)

    if daily.remaining() < cost:
        return Decision(False, messages.DAILY_CAP.format(limit=daily.limit))

    return Decision(True)


def record_action(session: SessionUsage, *, monotonic: float) -> None:
    session.actions += 1
    session.last_action_at = monotonic


def allowance_caption(session: SessionUsage, daily: DailyCounter) -> str:
    left_in_session = max(0, MAX_SESSION_ACTIONS - session.actions)
    return (
        f"{left_in_session} of {MAX_SESSION_ACTIONS} generations left in this session · "
        f"{daily.remaining()} of {daily.limit} requests left today"
    )


LIMITATION_NOTE = (
    "These caps are counted in the running app's own memory. Streamlit Community Cloud "
    f"sleeps an app after {config.SLEEP_HOURS} hours without traffic and restarts it on "
    "redeploy, and the count resets whenever that happens. If the platform ever runs more "
    "than one process for this app, each would count separately. So this is a guard "
    "against accidental overuse, not a hard limit — the real backstop is the provider "
    "refusing further requests, which the app reports as the daily limit being reached."
)
