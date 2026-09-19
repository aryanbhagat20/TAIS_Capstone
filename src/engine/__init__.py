"""
engine — TAIS Trust-Scoring Engine.

Exports:
    TrustScoringEngine: Main engine class.
    ScoringConfig: Tuneable rule thresholds and weights.
    RuleResult: Per-rule evaluation result.
"""
from src.engine.trust_scoring_engine import (
    TrustScoringEngine,
    ScoringConfig,
    RuleResult,
)
