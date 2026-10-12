"""Quota guards. No sleeping: the clock is injected."""

import threading
from datetime import datetime, timedelta, timezone

import pytest

from podcast_compass import messages, quota
from podcast_compass.llm import Outcome
from podcast_compass.quota import (
    MAX_DAILY_REQUESTS,
    MAX_SESSION_ACTIONS,
    MIN_SECONDS_BETWEEN_ACTIONS,
    REQUESTS_PER_ACTION,
    DailyCounter,
    Decision,
    SessionUsage,
    allowance_caption,
    check,
    record_action,
)

START = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, at: datetime = START) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kwargs) -> None:
        self.at += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def daily(clock) -> DailyCounter:
    return DailyCounter(now=clock)


class TestRequestsPerAction:
    def test_worst_case_action_costs_three_requests(self):
        assert REQUESTS_PER_ACTION == 3

    def test_outcome_reports_a_plain_call_as_one_request(self):
        outcome = Outcome("m", 10.0, used_fallback=False, repaired=False)
        assert outcome.requests == 1

    def test_outcome_counts_the_fallback(self):
        assert Outcome("m", 10.0, used_fallback=True, repaired=False).requests == 2

    def test_outcome_counts_fallback_and_repair(self):
        assert Outcome("m", 10.0, used_fallback=True, repaired=True).requests == 3


class TestDailyCounter:
    def test_starts_empty(self, daily):
        assert daily.used() == 0
        assert daily.remaining() == MAX_DAILY_REQUESTS

    def test_reserve_takes_from_the_budget(self, daily):
        assert daily.reserve(3) is True
        assert daily.used() == 3
        assert daily.remaining() == MAX_DAILY_REQUESTS - 3

    def test_settle_refunds_what_was_not_used(self, daily):
        daily.reserve(3)
        daily.settle(reserved=3, actual=1)
        assert daily.used() == 1

    def test_release_refunds_everything(self, daily):
        daily.reserve(3)
        daily.release(3)
        assert daily.used() == 0

    def test_reserve_refuses_when_the_budget_would_be_exceeded(self, clock):
        small = DailyCounter(limit=4, now=clock)
        assert small.reserve(3) is True
        assert small.reserve(3) is False
        # The refused reservation must not have been charged.
        assert small.used() == 3

    def test_reserve_allows_exactly_reaching_the_limit(self, clock):
        small = DailyCounter(limit=6, now=clock)
        assert small.reserve(3) is True
        assert small.reserve(3) is True
        assert small.remaining() == 0
        assert small.reserve(1) is False

    def test_counter_resets_on_a_new_utc_day(self, clock, daily):
        daily.reserve(10)
        assert daily.used() == 10
        clock.advance(days=1)
        assert daily.used() == 0
        assert daily.remaining() == MAX_DAILY_REQUESTS

    def test_same_day_later_does_not_reset(self, clock, daily):
        daily.reserve(10)
        clock.advance(hours=6)
        assert daily.used() == 10

    def test_settle_cannot_push_usage_negative(self, daily):
        daily.reserve(1)
        daily.settle(reserved=3, actual=0)
        assert daily.used() == 0

    def test_concurrent_reservations_never_exceed_the_limit(self, clock):
        # 30 threads each wanting 3 requests from a budget of 30: exactly 10 win.
        counter = DailyCounter(limit=30, now=clock)
        granted: list[bool] = []
        lock = threading.Lock()

        def attempt() -> None:
            ok = counter.reserve(3)
            with lock:
                granted.append(ok)

        threads = [threading.Thread(target=attempt) for _ in range(30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(granted) == 10
        assert counter.used() == 30
        assert counter.remaining() == 0


class TestCheck:
    def test_allows_a_first_action(self, daily):
        assert check(SessionUsage(), daily, monotonic=100.0) == Decision(True)

    def test_blocks_once_the_session_cap_is_reached(self, daily):
        session = SessionUsage(actions=MAX_SESSION_ACTIONS, last_action_at=0.0)
        decision = check(session, daily, monotonic=10_000.0)
        assert decision.allowed is False
        assert "this session" in decision.message

    def test_allows_the_last_action_under_the_cap(self, daily):
        session = SessionUsage(actions=MAX_SESSION_ACTIONS - 1, last_action_at=0.0)
        assert check(session, daily, monotonic=10_000.0).allowed is True

    def test_blocks_a_second_action_too_soon(self, daily):
        session = SessionUsage(actions=1, last_action_at=100.0)
        decision = check(session, daily, monotonic=100.0 + MIN_SECONDS_BETWEEN_ACTIONS / 2)
        assert decision.allowed is False
        assert decision.message == messages.TOO_SOON

    def test_allows_once_the_gap_has_passed(self, daily):
        session = SessionUsage(actions=1, last_action_at=100.0)
        assert check(
            session, daily, monotonic=100.0 + MIN_SECONDS_BETWEEN_ACTIONS
        ).allowed is True

    def test_blocks_when_the_day_has_too_little_left(self, clock):
        session = SessionUsage()
        nearly_spent = DailyCounter(limit=2, now=clock)
        decision = check(session, nearly_spent, monotonic=100.0)
        assert decision.allowed is False
        assert "free tier" in decision.message

    def test_session_cap_is_reported_before_the_daily_cap(self, clock):
        # A user who has used their own allowance should be told that, not blamed on
        # the shared one.
        session = SessionUsage(actions=MAX_SESSION_ACTIONS)
        spent = DailyCounter(limit=0, now=clock)
        assert "this session" in check(session, spent, monotonic=100.0).message


class TestRecordAction:
    def test_increments_and_stamps(self):
        session = SessionUsage()
        record_action(session, monotonic=500.0)
        assert session.actions == 1
        assert session.last_action_at == 500.0

    def test_ten_actions_then_blocked(self, daily):
        session = SessionUsage()
        now = 0.0
        for _ in range(MAX_SESSION_ACTIONS):
            now += MIN_SECONDS_BETWEEN_ACTIONS
            assert check(session, daily, monotonic=now).allowed is True
            record_action(session, monotonic=now)
        now += MIN_SECONDS_BETWEEN_ACTIONS
        assert check(session, daily, monotonic=now).allowed is False


class TestBlockedActionsCostNothing:
    def test_a_blocked_action_makes_no_call(self, daily):
        """The guard runs before the client is ever touched."""

        def must_not_be_called(**kwargs):
            raise AssertionError("a blocked action must not reach the provider")

        session = SessionUsage(actions=MAX_SESSION_ACTIONS)
        decision = check(session, daily, monotonic=100.0)
        assert decision.allowed is False
        if decision.allowed:  # pragma: no cover - guards the test's own logic
            must_not_be_called()
        # Nothing was reserved either, so the shared budget is untouched.
        assert daily.used() == 0

    def test_a_refused_reservation_leaves_the_budget_intact(self, clock):
        counter = DailyCounter(limit=2, now=clock)
        assert counter.reserve(3) is False
        assert counter.used() == 0
        assert counter.remaining() == 2


class TestAllowanceCaption:
    def test_reports_both_remaining_counts(self, daily):
        caption = allowance_caption(SessionUsage(actions=2), daily)
        assert f"{MAX_SESSION_ACTIONS - 2} of {MAX_SESSION_ACTIONS} generations left" in caption
        assert f"{MAX_DAILY_REQUESTS} of {MAX_DAILY_REQUESTS} requests left today" in caption

    def test_never_shows_a_negative_count(self, daily):
        caption = allowance_caption(SessionUsage(actions=MAX_SESSION_ACTIONS + 5), daily)
        assert "0 of 10 generations left" in caption


class TestLimitationIsStated:
    def test_note_admits_what_the_counter_cannot_do(self):
        note = quota.LIMITATION_NOTE.casefold()
        assert "own memory" in note
        assert "resets" in note
        assert "not a hard limit" in note
        assert "more than one process" in note

    def test_daily_cap_sits_under_the_providers_own_allowance(self):
        # 500 requests per day per model on the free tier; staying under it on the
        # primary alone means the fallback model's quota is untouched headroom.
        assert MAX_DAILY_REQUESTS < 500
