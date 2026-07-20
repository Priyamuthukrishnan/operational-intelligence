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
        if -1.0 <= score_val <= 1.0:
            return clamp_and_round(((score_val + 1.0) / 2.0) * 10.0)
        else:
            return clamp_and_round(score_val)
    except (ValueError, TypeError):
        return None

def convert_escalation_risk_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        if 0.0 <= score_val <= 1.0:
            return clamp_and_round(score_val * 10.0)
        else:
            return clamp_and_round(score_val)
    except (ValueError, TypeError):
        return None

def convert_root_cause_confidence(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        if 0.0 <= score_val <= 1.0:
            return clamp_and_round(score_val * 10.0)
        else:
            return clamp_and_round(score_val)
    except (ValueError, TypeError):
        return None

def convert_similarity_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        if 0.0 <= score_val <= 1.0:
            return clamp_and_round(score_val * 10.0)
        else:
            return clamp_and_round(score_val)
    except (ValueError, TypeError):
        return None

def convert_confidence_decay_score(score: Optional[Union[float, int]]) -> Optional[float]:
    if score is None:
        return None
    try:
        score_val = float(score)
        if 0.0 <= score_val <= 20.0:
            return clamp_and_round(score_val / 2.0)
        else:
            return clamp_and_round(score_val)
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

from core.logging import setup_logger

logger = setup_logger(__name__)

def sentiment_label_from_score(score: Optional[Union[float, int]]) -> Optional[str]:
    """Derive an aggregate sentiment label from a canonical average sentiment score in [-1.0, 1.0].

    Uses the canonical polarity thresholds:
      score > 0  → "positive"
      score < 0  → "negative"
      score == 0 → "neutral"

    Returns None when score is None.
    """
    if score is None:
        return None
    try:
        val = float(score)
    except (ValueError, TypeError):
        return None

    if val < -1.0 or val > 1.0:
        logger.warning(
            "sentiment_label_from_score received out-of-bounds sentiment score %.2f (expected [-1.0, 1.0])",
            val,
        )

    if val > 0:
        return "positive"
    if val < 0:
        return "negative"
    return "neutral"


CENTRALIZED_CATEGORY_MAP = {
    "user_error": "User Error",
    "software_bug": "Software Bug",
    "access_permission": "Access Management",
    "performance_degradation": "Performance Degradation",
    "integration_failure": "Integration Failure"
}

def normalize_category_name(category: Optional[str]) -> Optional[str]:
    if not category:
        return category
    cleaned = category.strip().lower()
    if cleaned in CENTRALIZED_CATEGORY_MAP:
        return CENTRALIZED_CATEGORY_MAP[cleaned]
    
    # Check other synonyms or replacements
    synonyms = {
        "access_management": "Access Management",
        "service_outage": "Service Outage",
        "performance": "Performance Degradation",
        "reporting": "Reporting",
        "database": "Database",
        "network": "Network",
        "general_support": "General Support",
        "erp": "ERP Integration Failures",
        "finance": "Finance"
    }
    if cleaned in synonyms:
        return synonyms[cleaned]
    
    # Fallback to no snake_case
    return category.replace("_", " ").replace("-", " ").title()

