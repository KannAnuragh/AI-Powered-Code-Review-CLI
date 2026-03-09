"""Specialized review agents for multi-agent pipeline.

Each agent focuses on a single domain (security, logic, performance)
and returns raw finding dicts. SynthesisAgent merges them into the
final CodeReviewResult.
"""

from .security import SecurityAgent
from .logic import LogicAgent
from .performance import PerformanceAgent
from .synthesizer import SynthesisAgent

__all__ = ["SecurityAgent", "LogicAgent", "PerformanceAgent", "SynthesisAgent"]
