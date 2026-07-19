#!/usr/bin/env python3
"""Pluggable microphone audio front-end and transparent session wrapper.

P1a deliberately keeps ``passthrough`` as the default production mode. The
optional ``basic`` mode only performs conservative signal conditioning (DC
blocking + slowly-smoothed RMS level control); it is not a full noise suppressor
or acoustic echo canceller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import wave

import numpy