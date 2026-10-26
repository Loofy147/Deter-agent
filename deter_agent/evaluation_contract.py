"""Shared evaluation contract constants used by the harness and registry."""
HARD_COMPONENTS = (
    "determinism_score", "regression_score", "policy_score", "schema_score",
    "state_transition_score", "tie_break_score", "failure_path_score",
)
TEST_COMPONENT = {
    "determinism": "determinism_score",
    "regression": "regression_score",
    "policy": "policy_score",
    "schema": "schema_score",
    "state_transition": "state_transition_score",
    "tie_break": "tie_break_score",
    "failure_path": "failure_path_score",
}
SUPPLEMENTAL_TEST_TYPES = ("threshold_boundary", "approval_binding")
REQUIRED_TEST_TYPES = tuple(TEST_COMPONENT) + SUPPLEMENTAL_TEST_TYPES

def performance_score_from_latencies(latencies, maximum_latency_ms):
    """Return a score derived from measured per-case latency, or None without a valid SLA."""
    import math

    if (
        isinstance(maximum_latency_ms, bool)
        or not isinstance(maximum_latency_ms, (int, float))
        or not math.isfinite(maximum_latency_ms)
        or maximum_latency_ms <= 0
    ):
        return None
    values = list(latencies)
    if not values:
        return None
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return None
    observed_max = max(values)
    if observed_max <= 0 or observed_max <= maximum_latency_ms:
        return 1.0
    return float(maximum_latency_ms / observed_max)
