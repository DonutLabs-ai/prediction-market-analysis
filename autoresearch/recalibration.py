"""
Logit-based two-step domain-specific recalibration following Nam Anh Le (2026).

Core formula:
    logit(P*) = α_d + β_d · logit(p)
    P* = sigmoid(logit(P*))

Where:
    - p: market price (implied probability)
    - P*: recalibrated true probability
    - α_d: domain intercept (Table 6)
    - β_d: domain × horizon slope (Table 3)
    - logit(x) = log(x / (1-x))
    - sigmoid(x) = 1 / (1 + exp(-x))
"""

import numpy as np
from typing import Union, Optional

try:
    from autoresearch.calibration_parameters import (
        get_calibration_slope,
        get_domain_intercept,
        get_horizon_label,
    )
except ImportError:
    # Fallback for direct execution
    from calibration_parameters import (
        get_calibration_slope,
        get_domain_intercept,
        get_horizon_label,
    )


def logit(p: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """
    Compute logit(p) = log(p / (1-p)).

    Handles edge cases:
    - p ≤ 0: returns -∞ (clamped to -10)
    - p ≥ 1: returns +∞ (clamped to +10)
    - 0 < p < 1: returns exact logit
    """
    p = np.asarray(p, dtype=np.float64)
    # Clip to [0.001, 0.999] to avoid log(0)
    p = np.clip(p, 0.001, 0.999)
    return np.log(p / (1 - p))


def sigmoid(x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """
    Compute sigmoid(x) = 1 / (1 + exp(-x)).

    Handles numerical stability:
    - x < -100: returns ≈ 0
    - x > 100: returns ≈ 1
    - -100 ≤ x ≤ 100: returns exact sigmoid
    """
    x = np.asarray(x, dtype=np.float64)
    return 1.0 / (1.0 + np.exp(-np.clip(x, -100, 100)))


def recalibrate_probability(
    market_price: float,
    domain: str,
    hours_to_expiration: float,
    use_intercept: bool = True,
) -> dict:
    """
    Apply two-step domain-specific recalibration to market price.

    Args:
        market_price: Market's implied probability (0 to 1)
        domain: Category ('politics', 'sports', 'crypto', 'finance', 'weather', 'entertainment')
        hours_to_expiration: Time until market resolution (hours)
        use_intercept: If True, apply domain intercept α_d. If False, apply only slope β_d.

    Returns:
        dict with:
            - 'market_price': original input
            - 'recalibrated_prob': P* (recalibrated true probability)
            - 'edge': P* - p (expected value if you buy YES at market price)
            - 'domain': domain used
            - 'horizon': horizon bucket
            - 'alpha': domain intercept applied
            - 'beta': calibration slope applied
            - 'logit_market': logit(p)
            - 'logit_recal': logit(P*)

    Example:
        >>> recalibrate_probability(0.70, 'politics', hours_to_expiration=120)
        {
            'market_price': 0.70,
            'recalibrated_prob': 0.811,
            'edge': +0.111,
            'domain': 'politics',
            'horizon': '2d-1w',
            'alpha': +0.151,
            'beta': 1.83,
            ...
        }
    """
    # Validate inputs
    market_price = float(np.clip(market_price, 0.001, 0.999))
    domain = domain.lower()

    # Get parameters
    alpha = get_domain_intercept(domain) if use_intercept else 0.0
    beta = get_calibration_slope(domain, hours_to_expiration)
    horizon = get_horizon_label(hours_to_expiration)

    # Step 1: Apply logit transform to market price
    logit_p = logit(market_price)

    # Step 2: Apply two-step recalibration in logit space
    logit_p_star = alpha + beta * logit_p

    # Step 3: Convert back to probability space
    p_star = sigmoid(logit_p_star)

    # Edge: expected value per unit bet
    edge = p_star - market_price

    return {
        "market_price": market_price,
        "recalibrated_prob": float(p_star),
        "edge": float(edge),
        "domain": domain,
        "horizon": horizon,
        "hours_to_expiration": hours_to_expiration,
        "alpha": float(alpha),
        "beta": float(beta),
        "logit_market": float(logit_p),
        "logit_recal": float(logit_p_star),
        "use_intercept": use_intercept,
    }


def trading_signal(
    market_price: float,
    domain: str,
    hours_to_expiration: float,
    min_edge: float = 0.02,
    use_intercept: bool = True,
) -> dict:
    """
    Generate a trading signal based on recalibrated probability.

    Args:
        market_price: Market price (0 to 1)
        domain: Category
        hours_to_expiration: Time until resolution (hours)
        min_edge: Minimum edge (|P* - p|) to trigger a trade
        use_intercept: Apply domain intercept?

    Returns:
        dict with:
            - 'signal': 'BUY_YES' | 'BUY_NO' | 'PASS'
            - 'confidence': edge magnitude (0 to 1)
            - 'recal': full recalibration result dict

    Example:
        >>> trading_signal(0.25, 'politics', 168)
        {
            'signal': 'BUY_YES',
            'confidence': 0.08,
            'reason': 'Political YES underpriced by 8¢',
            'recal': {...}
        }
    """
    recal = recalibrate_probability(market_price, domain, hours_to_expiration, use_intercept)
    edge = recal["edge"]

    if abs(edge) < min_edge:
        signal = "PASS"
        reason = f"Edge {abs(edge):.3f} < threshold {min_edge:.3f}"
    elif edge > 0:
        signal = "BUY_YES"
        reason = f"{domain.title()} YES underpriced by {abs(edge):.1%}"
    else:
        signal = "BUY_NO"
        reason = f"{domain.title()} YES overpriced by {abs(edge):.1%}"

    return {
        "signal": signal,
        "confidence": float(abs(edge)),
        "reason": reason,
        "recal": recal,
    }


# ============================================================================
# TESTING & EXAMPLES
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("RECALIBRATION EXAMPLES")
    print("=" * 80)

    examples = [
        {
            "name": "Politics: Short-term, extreme YES",
            "market_price": 0.15,
            "domain": "politics",
            "hours_to_expiration": 6,
        },
        {
            "name": "Politics: Long-term, moderate YES",
            "market_price": 0.70,
            "domain": "politics",
            "hours_to_expiration": 120,  # 5 days
        },
        {
            "name": "Weather: Short-term, high YES",
            "market_price": 0.85,
            "domain": "weather",
            "hours_to_expiration": 12,
        },
        {
            "name": "Sports: Long-term, balanced",
            "market_price": 0.50,
            "domain": "sports",
            "hours_to_expiration": 720,  # 30 days
        },
    ]

    for example in examples:
        result = recalibrate_probability(
            example["market_price"], example["domain"], example["hours_to_expiration"]
        )
        signal = trading_signal(
            example["market_price"],
            example["domain"],
            example["hours_to_expiration"],
            min_edge=0.02,
        )

        print(f"\n{example['name']}")
        print(f"  Market price: {example['market_price']:.1%}")
        print(f"  Horizon: {result['horizon']}")
        print(f"  α (intercept): {result['alpha']:+.3f}")
        print(f"  β (slope): {result['beta']:.2f}")
        print(f"  Recalibrated: {result['recalibrated_prob']:.1%}")
        print(f"  Edge: {result['edge']:+.1%}")
        print(f"  Signal: {signal['signal']} ({signal['reason']})")
