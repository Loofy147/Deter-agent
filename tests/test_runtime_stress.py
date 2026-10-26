"""Adversarial stress tests for request dedupe, approval expiry and immutable evidence."""
from __future__ import annotations

import sqlite3
import threading
import time
import unittest

from deter_agent.gateway import PermissionGateway
from deter_agent.registry import Registry
from deter_agent.runtime import RuntimeEngine
from tests.helpers import make_policy, make_spec, make_tool_catalog, register_version_everywhere


class RuntimeStressTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.spec = make_spec()
        register_version_everywhere(self.registry, self.spec)
        self.gateway = PermissionGateway(self.registry, make_tool_catalog())

    def tearDown(self):
        self.registry.close()

    @staticmethod
    def job(request_id, intent="do", environment="staging"):
        return {
            "request_id": request_id,
            "agent_id": "agent-a",
            "agent_version": "v1.0.0",
            "environment": environment,
            "requested_by": "test-requester",
            "input": {"received_at": "2026-10-26T12:00:00Z", "intent": intent},
        }

    def test_concurrent_duplicate_request_has_at_most_one_effect(self):
        calls = []
        lock = threading.Lock()
        start = threading.Barrier(3)

        def handler(action_input, idempotency_key=None):
            with lock:
                calls.append(idempotency_key)
            # Widen the race window between request lookup and final result storage.
            time.sleep(0.05)
            return {"ok": True, "ticket_id": "T-CONCURRENT", "new_state": {"last_intent": "do"}}

        runtime = RuntimeEngine(self.registry, self.gateway, {"create_ticket": handler})
        results = []

        def invoke():
            start.wait()
            results.append(runtime.run(self.job("same-logical-request")))

        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads), "worker hung")
        self.assertEqual(len(results), 2)
        self.assertEqual(len(calls), 1, "duplicate logical request caused multiple external effects")
        self.assertEqual(sum(result["status"] == "completed" for result in results), 1)
        self.assertEqual(self.registry.load_state("agent-a", "same-logical-request")[1], 1)

    def test_expired_approval_cannot_resume_frozen_action(self):
        calls = []

        def send(action_input, idempotency_key=None):
            calls.append(action_input)
            return {"ok": True, "message_id": "M-EXPIRED"}

        runtime = RuntimeEngine(self.registry, self.gateway, {"send_message": send})
        pending = runtime.run(self.job("expired-approval", "protected", "production"))
        self.assertEqual(pending["status"], "approval_pending")
        frozen = self.registry.get_frozen_decision(pending["decision_id"])
        approval = self.registry.record_approval(
            target_type="runtime_action",
            target_id=pending["decision_id"],
            agent_id="agent-a",
            version="v1.0.0",
            target_environment="production",
            requested_by="requester",
            approver="independent-reviewer",
            decision="approved",
            spec_hash=frozen["spec_hash"],
            eval_run_id=None,
            expires_at=time.time() - 1,
            policy_diff_hash=pending["policy_diff_hash"],
            scope=pending["approval_scope"],
        )
        resumed = runtime.resume_approved(pending["decision_id"], approval["approval_id"])
        self.assertEqual(resumed["status"], "rejected")
        self.assertEqual(resumed["reason_code"], "APPROVAL_MISMATCH")
        self.assertEqual(calls, [], "expired approval executed an external action")
        self.assertEqual(self.registry.load_state("agent-a", "expired-approval")[1], 0)

    def test_trace_and_approval_evidence_are_append_only(self):
        runtime = RuntimeEngine(self.registry, self.gateway, {"create_ticket": lambda payload, idempotency_key=None: {"ok": True, "ticket_id": "T-IMMUTABLE"}})
        result = runtime.run(self.job("immutable-evidence"))
        self.assertEqual(result["status"], "completed")
        trace_id = self.registry._connection.execute(
            "SELECT trace_id FROM traces WHERE request_id=?", ("immutable-evidence",)
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry._connection.execute("UPDATE traces SET status='rewritten' WHERE trace_id=?", (trace_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry._connection.execute("DELETE FROM traces WHERE trace_id=?", (trace_id,))

        frozen_runtime = RuntimeEngine(self.registry, self.gateway, {"send_message": lambda payload: {"ok": True, "message_id": "M"}})
        pending = frozen_runtime.run(self.job("approval-evidence", "protected", "production"))
        self.assertEqual(pending["status"], "approval_pending")
        frozen = self.registry.get_frozen_decision(pending["decision_id"])
        approval = self.registry.record_approval(
            target_type="runtime_action", target_id=pending["decision_id"], agent_id="agent-a",
            version="v1.0.0", target_environment="production", requested_by="requester",
            approver="independent-reviewer", decision="approved", spec_hash=frozen["spec_hash"],
            eval_run_id=None, expires_at=time.time()+600,
            policy_diff_hash=pending["policy_diff_hash"], scope=pending["approval_scope"],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry._connection.execute(
                "UPDATE approval_events SET decision='rejected' WHERE approval_id=?", (approval["approval_id"],)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry._connection.execute(
                "DELETE FROM approval_events WHERE approval_id=?", (approval["approval_id"],)
            )


if __name__ == "__main__":
    unittest.main()
