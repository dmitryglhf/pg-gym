"""Stable cursors shared by HTTP collection endpoints."""
import math

from fastapi import HTTPException


def decode_cursor(cursor: str | None) -> tuple[float | None, str]:
    if cursor is None:
        return None, ""
    try:
        value, identifier = cursor.split(":", 1)
        stamp = float(value)
        if not identifier or not math.isfinite(stamp):
            raise ValueError
        return stamp, identifier
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid pagination cursor") from None
