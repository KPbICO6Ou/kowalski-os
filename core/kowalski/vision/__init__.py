"""Vision subsystem: screen capture + vision-LLM scene description.

Backs the screen.* READ tools. Screen content is sensitive, but capturing and
describing it does not mutate the system, so these are RiskLevel.READ.
"""

from __future__ import annotations

from .capture import MockScreenCapturer, ScreenCapturer, SystemScreenCapturer
from .describe import MockVisionModel, OllamaVisionModel, VisionModel

__all__ = [
    "ScreenCapturer",
    "SystemScreenCapturer",
    "MockScreenCapturer",
    "VisionModel",
    "OllamaVisionModel",
    "MockVisionModel",
]
