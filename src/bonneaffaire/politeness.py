"""Politeness: per-Provider throttling, a short response cache and backoff after a block, so
the home IP stays under anti-bot thresholds."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from bonneaffaire.providers import ProviderBlocked


class Clock(Protocol):
    def now(self) -> float:
        """Monotonic seconds."""
        ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True)
class Politeness:
    """How politely the core treats Providers. The defaults switch everything off.

    rates: requests per minute allowed per Provider name, overriding default_rate.
    default_rate: requests per minute for any other Provider; None means unthrottled.
    cache_seconds: how long a Provider's successful answer to an identical request is reused.
    backoff_seconds: how long a Provider that reported blocked is left alone; meanwhile it
    reports blocked without being asked.
    """

    rates: Mapping[str, float] = field(default_factory=dict)
    default_rate: float | None = None
    cache_seconds: float = 0.0
    backoff_seconds: float = 0.0

    def rate_for(self, provider: str) -> float | None:
        return self.rates.get(provider, self.default_rate)


class Guard:
    """Wraps every request the core makes to a Provider (Search, Get Listing)."""

    def __init__(self, policy: Politeness, clock: Clock) -> None:
        self._policy = policy
        self._clock = clock
        self._next_slot: dict[str, float] = {}
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._blocked_until: dict[str, float] = {}

    async def request[T](
        self, provider: str, call: Callable[[], Awaitable[T]], key: str | None = None
    ) -> T:
        """Make one request to `provider`, throttled, unless it is backing off after a block
        (then raise ProviderBlocked without asking it).

        key: the normalised request; a successful answer under the same key is reused for
        the cache window without asking the Provider. None means never cached.
        """
        self._check_backoff(provider)
        cache_key = None if key is None or self._policy.cache_seconds <= 0 else (provider, key)
        if cache_key is not None:
            hit = self._cache.get(cache_key)
            if hit is not None and self._clock.now() < hit[0]:
                return hit[1]
        await self._throttle(provider)
        try:
            answer = await call()
        except ProviderBlocked:
            if self._policy.backoff_seconds > 0:
                self._blocked_until[provider] = self._clock.now() + self._policy.backoff_seconds
            raise
        if cache_key is not None:
            self._cache[cache_key] = (self._clock.now() + self._policy.cache_seconds, answer)
        return answer

    def _check_backoff(self, provider: str) -> None:
        until = self._blocked_until.get(provider)
        if until is None:
            return
        left = until - self._clock.now()
        if left <= 0:
            del self._blocked_until[provider]
            return
        raise ProviderBlocked(provider, f"backing off after a block, {left:.0f}s left")

    async def _throttle(self, provider: str) -> None:
        """Reserve the Provider's next free request slot, then wait for it.

        Reserving before waiting keeps concurrent callers spaced out without a lock.
        """
        rate = self._policy.rate_for(provider)
        if rate is None:
            return
        now = self._clock.now()
        slot = max(now, self._next_slot.get(provider, now))
        self._next_slot[provider] = slot + 60.0 / rate
        if slot > now:
            await self._clock.sleep(slot - now)
