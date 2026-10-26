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
