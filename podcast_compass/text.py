"""Small text helpers shared by the validator and the interface."""

from __future__ import annotations


def plural(count: int, noun: str, suffix: str = "s") -> str:
    """"1 segment" / "3 segments". Used anywhere a count reaches a user."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}{suffix}"
