"""Shared availability metrics for the SIP downdetector prototype."""

from math import sqrt


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def mean(values, default=1.0):
    return sum(values) / len(values) if values else default


def sample_std(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance)


def moving_average(values, window=5):
    if not values:
        return 1.0
    recent = values[-window:] if len(values) >= window else values
    return clamp(mean(recent))


def ewma_forecast(values, alpha=0.35):
    """One-step-ahead forecast using exponential smoothing."""
    if not values:
        return 1.0

    estimate = values[0]
    for value in values[1:]:
        estimate = alpha * value + (1 - alpha) * estimate
    return clamp(estimate)


def mean_confidence_interval(values, confidence_z=1.96):
    """Normal-approximation confidence interval for average availability."""
    if not values:
        return (1.0, 1.0)
    avg = mean(values)
    if len(values) < 2:
        return (clamp(avg), clamp(avg))
    margin = confidence_z * sample_std(values) / sqrt(len(values))
    return (clamp(avg - margin), clamp(avg + margin))


def incident_rate(values, threshold=0.7):
    if not values:
        return 0.0
    incidents = sum(1 for value in values if value < threshold)
    return incidents / len(values)


def anomaly_score(values, window=10):
    """Positive z-score of the latest drop against the previous window."""
    if len(values) < 3:
        return 0.0
    baseline = values[-window - 1:-1] if len(values) > window else values[:-1]
    baseline_mean = mean(baseline)
    baseline_std = sample_std(baseline)
    if baseline_std == 0:
        return 1.0 if values[-1] < baseline_mean else 0.0
    return max(0.0, (baseline_mean - values[-1]) / baseline_std)


def risk_score(values, forecast=None):
    """Weighted risk model: forecast deficit + volatility + incident density."""
    if not values:
        return 0.0

    forecast_value = ewma_forecast(values) if forecast is None else forecast
    volatility = sample_std(values)
    incidents = incident_rate(values)
    score = 0.55 * (1 - forecast_value) + 0.25 * volatility + 0.20 * incidents
    return clamp(score)


def classify_risk(score):
    if score >= 0.50:
        return 'HIGH'
    if score >= 0.25:
        return 'MEDIUM'
    return 'LOW'


def availability_status(avg_availability):
    if avg_availability >= 0.9:
        return 'ok'
    if avg_availability >= 0.5:
        return 'degraded'
    return 'down'


def compute_availability_stats(values):
    avg = mean(values)
    sma = moving_average(values)
    ewma = ewma_forecast(values)
    ci_low, ci_high = mean_confidence_interval(values)
    volatility = sample_std(values)
    score = risk_score(values, ewma)

    return {
        'current_status': availability_status(avg),
        'uptime_24h': round(avg, 3),
        'prediction': round(sma, 3),
        'ewma_prediction': round(ewma, 3),
        'availability_ci_low': round(ci_low, 3),
        'availability_ci_high': round(ci_high, 3),
        'volatility': round(volatility, 3),
        'incident_rate': round(incident_rate(values), 3),
        'anomaly_score': round(anomaly_score(values), 3),
        'risk_score': round(score, 3),
        'risk': classify_risk(score),
    }
