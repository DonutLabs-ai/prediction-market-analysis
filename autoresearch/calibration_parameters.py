"""
Calibration parameters from Nam Anh Le (2026): "The Microstructure of Prediction Markets"
arXiv:2602.19520

This module defines:
- Table 3: Logistic recalibration slopes β by domain and time-to-resolution
- Table 6: Domain intercepts α (Bayesian posterior estimates)
- Table 4: Trade size effects
- Horizon bins and labels for stratification

Reference:
Le, N. A. (2026). The Microstructure of Prediction Markets. arXiv preprint arXiv:2602.19520.
Data: Kalshi platform, 292M trades, 6 domains, 6 time horizons.
"""

import numpy as np
from typing import Tuple, Dict, List

# ============================================================================
# TABLE 3: LOGISTIC RECALIBRATION SLOPES β BY DOMAIN × HORIZON
# ============================================================================
# β > 1.0: underconfidence (market prices too compressed toward 50%)
# β < 1.0: overconfidence (market prices too extreme)
# β = 1.0: perfect calibration

CALIBRATION_SLOPES = {
    "politics": [1.34, 0.93, 1.32, 1.55, 1.48, 1.52, 1.83, 1.83, 1.73],
    "sports": [1.10, 0.96, 0.90, 1.01, 1.05, 1.08, 1.04, 1.24, 1.74],
    "crypto": [0.99, 1.01, 1.07, 1.01, 1.01, 1.21, 1.12, 1.09, 1.36],
    "finance": [0.96, 1.07, 1.03, 0.97, 0.98, 0.82, 1.07, 1.42, 1.20],
    "weather": [0.69, 0.84, 0.74, 0.87, 0.91, 0.97, 1.20, 1.20, 1.37],
    "entertainment": [0.81, 1.02, 1.00, 0.92, 0.89, 0.84, 1.07, 1.11, 0.96],
}

# ============================================================================
# TABLE 6: DOMAIN INTERCEPTS α (Bayesian Posterior Means)
# ============================================================================
# α: intercept in logit space. Represents systematic domain-level bias
# α > 0: underconfidence (market underestimates probabilities)
# α < 0: overconfidence (market overestimates probabilities)
# 95% CI shown for reference; use point estimate for trading

DOMAIN_INTERCEPTS = {
    "politics": {
        "mean": +0.151,
        "std": 0.015,
        "ci_lower": +0.122,
        "ci_upper": +0.179,
        "interpretation": "Strong underconfidence: market prices political YES contracts 15¢ too low",
    },
    "sports": {
        "mean": +0.010,
        "std": 0.015,
        "ci_lower": -0.020,
        "ci_upper": +0.039,
        "interpretation": "Nearly unbiased; slight underconfidence",
    },
    "crypto": {
        "mean": +0.005,
        "std": 0.015,
        "ci_lower": -0.024,
        "ci_upper": +0.034,
        "interpretation": "Nearly unbiased; minimal systematic bias",
    },
    "finance": {
        "mean": +0.006,
        "std": 0.015,
        "ci_lower": -0.023,
        "ci_upper": +0.035,
        "interpretation": "Nearly unbiased; minimal systematic bias",
    },
    "weather": {
        "mean": -0.086,
        "std": 0.015,
        "ci_lower": -0.115,
        "ci_upper": -0.057,
        "interpretation": "Strong overconfidence: market prices weather YES contracts 8.6¢ too high",
    },
    "entertainment": {
        "mean": -0.085,
        "std": 0.015,
        "ci_lower": -0.114,
        "ci_upper": -0.056,
        "interpretation": "Strong overconfidence: market prices entertainment YES contracts 8.5¢ too high",
    },
}

# ============================================================================
# HORIZON STRATIFICATION
# ============================================================================

HORIZON_BINS = [0, 1, 3, 6, 12, 24, 48, 7 * 24, 30 * 24, np.inf]
HORIZON_LABELS = ["0-1h", "1-3h", "3-6h", "6-12h", "12-24h", "24-48h", "2d-1w", "1w-1m", "1m+"]
HORIZON_NAMES = {
    "0-1h": "0–1 hour",
    "1-3h": "1–3 hours",
    "3-6h": "3–6 hours",
    "6-12h": "6–12 hours",
    "12-24h": "12–24 hours",
    "24-48h": "24–48 hours",
    "2d-1w": "2 days–1 week",
    "1w-1m": "1 week–1 month",
    "1m+": "1 month+",
}

# ============================================================================
# TABLE 4: TRADE SIZE EFFECTS (Politics as example)
# ============================================================================
# Large trades (>$100K) exhibit amplified calibration effects
# Effect is domain-specific; Politics shows strongest size effect

TRADE_SIZE_EFFECTS = {
    "politics": {
        "single": 1.19,
        "small": 1.22,
        "medium": 1.37,
        "large": 1.74,
        "delta_large_minus_small": 0.53,
        "delta_ci": [0.29, 0.75],
    },
    "sports": {
        "single": 1.00,
        "small": 1.01,
        "medium": 1.01,
        "large": 1.01,
        "delta_large_minus_small": 0.07,
    },
    "weather": {
        "single": 0.96,
        "small": 0.94,
        "medium": 0.91,
        "large": 0.89,
        "delta_large_minus_small": -0.07,
    },
}


# ============================================================================
# LOOKUP FUNCTIONS
# ============================================================================


def get_horizon_index(hours_to_expiration: float) -> int:
    """Map hours to horizon index (0-8) for Table 3 lookups."""
    import pandas as pd

    bins = [0, 1, 3, 6, 12, 24, 48, 7 * 24, 30 * 24, np.inf]
    idx = pd.cut([hours_to_expiration], bins=bins, labels=False)[0]
    return int(idx) if idx >= 0 else 0


def get_horizon_label(hours_to_expiration: float) -> str:
    """Return horizon label string."""
    idx = get_horizon_index(hours_to_expiration)
    return HORIZON_LABELS[idx]


def get_calibration_slope(
    domain: str, hours_to_expiration: float
) -> float:
    """
    Look up logistic recalibration slope β from Table 3.

    Args:
        domain: One of 'politics', 'sports', 'crypto', 'finance', 'weather', 'entertainment'
        hours_to_expiration: Time until market resolution (hours)

    Returns:
        β: Logistic slope parameter
            > 1.0: underconfidence (prices too compressed)
            < 1.0: overconfidence (prices too extreme)
            = 1.0: perfect calibration

    Example:
        >>> get_calibration_slope('politics', hours_to_expiration=120)  # 5 days
        1.83  # Politics markets 5d out are heavily underconfident
    """
    domain = domain.lower()
    if domain not in CALIBRATION_SLOPES:
        raise ValueError(
            f"Unknown domain '{domain}'. Must be one of {list(CALIBRATION_SLOPES.keys())}"
        )

    idx = get_horizon_index(hours_to_expiration)
    return CALIBRATION_SLOPES[domain][idx]


def get_domain_intercept(domain: str) -> float:
    """
    Look up domain intercept α from Table 6.

    Args:
        domain: One of 'politics', 'sports', 'crypto', 'finance', 'weather', 'entertainment'

    Returns:
        α: Domain intercept in logit space
            > 0: market underestimates true probabilities
            < 0: market overestimates true probabilities

    Example:
        >>> get_domain_intercept('politics')
        +0.151  # Political YES contracts priced 15.1¢ too low on average
    """
    domain = domain.lower()
    if domain not in DOMAIN_INTERCEPTS:
        raise ValueError(
            f"Unknown domain '{domain}'. Must be one of {list(DOMAIN_INTERCEPTS.keys())}"
        )
    return DOMAIN_INTERCEPTS[domain]["mean"]


# ============================================================================
# SUMMARY
# ============================================================================

DOMAINS = list(CALIBRATION_SLOPES.keys())
NUM_HORIZONS = len(HORIZON_LABELS)
NUM_DOMAINS = len(DOMAINS)

print(
    f"Calibration parameters loaded: {NUM_DOMAINS} domains × {NUM_HORIZONS} horizons "
    f"= {NUM_DOMAINS * NUM_HORIZONS} calibration cells"
)
