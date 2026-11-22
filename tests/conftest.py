"""Test runtime compatibility for Python 3.13 on restricted Windows hosts."""
import asyncio
import sys


if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
