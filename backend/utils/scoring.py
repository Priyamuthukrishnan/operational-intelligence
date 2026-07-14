"""
utils/scoring.py
Utility helper functions containing algorithms and math rules for calculating customer health scores and risk indicators.
"""

from typing import Optional, Union

def clamp_and_round(value: Optional[Union[float, int]]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(max(0.0, min(10.0, float(value))), 2)
    except (ValueError, TypeError):
        return None

def convert_sentiment_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        return clamp_and_round(((score_val + 1.0) / 2.0) * 10.0)
    except (ValueError, TypeError):
        return None

def convert_escalation_risk_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        return clamp_and_round(score_val * 10.0)
    except (ValueError, TypeError):
        return None

def convert_root_cause_confidence(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        return clamp_and_round(score_val * 10.0)
    except (ValueError, TypeError):
        return None

def convert_similarity_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        return clamp_and_round(score_val * 10.0)
    except (ValueError, TypeError):
        return None

def convert_confidence_decay_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        return clamp_and_round(score_val / 2.0)
    except (ValueError, TypeError):
        return None

def convert_health_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        return clamp_and_round(score_val / 10.0)
    except (ValueError, TypeError):
        return None
