#!/usr/bin/env python3
"""Pluggable microphone audio front-end and transparent session wrapper.

P1a deliberately keeps ``passthrough`` as the default production mode.  The
optional ``basic`` mode only performs conservative signal conditioning (DC
blocking + slowly-smoothed RMS level control); it is not presented as a full
noise suppressor or AEC implementation.
"""
from __future__ import annotations

from