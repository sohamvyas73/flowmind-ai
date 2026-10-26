import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.core.auth import get_current_user
from app.core.config import settings
from app.services.workflow_executor import NodeExecutor, WorkflowExecutor

GRAPH = {
    "nodes": [
        {"id": "in", "type": "inputNode", "data": {}},
        {"id": "code", "type": "codeNode", "data": {"code": "output = {'v': input_data['value'] + 1}"}},
        {"id": "out", "type": "outputNode", "data": {}},
    ],
    "edges": [
        {"id": "e1", "source": "in", "target": "code"},
        {"id": "e2", "source": "code", "target": "out"},
    ],
}


class CodeRunnerFlagTests(IsolatedAsyncioTestCase):
    def test_flag_defaults_to_false(self):
        self.assertFalse(type(settings).model_fields["ENABLE_CODE_NODE"].default)

    async def test_disabled_node_is_skipped_without_executing(self):
        with patch.object(settings, "ENABLE_CODE_NODE", False):
            result = await NodeExecutor().execute_code_node(
                {"code": "output = 123"},
                {"current_node_id": "c", "previous_output": {"value": 1}},
            )
        self.assertNotIn("error", result)
        self.assertTrue(result["skipped"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["output"], {"value": 1})  # input passed through
        self.assertIn("disabled", result["warning"].lower())

    async def test_enabled_node_runs(self):
        with patch.object(settings, "ENABLE_CODE_NODE", True):
            result = await NodeExecutor().execute_code_node(
                {"code": "output = input_data['value'] + 1", "timeout": 2},
                {"current_node_id": "c", "previous_output": {"value": 1}},
            )
        self.assertEqual(result["output"], 2)
        self.assertTrue(result["executed"])

    async def test_disabled_node_does_not_halt_workflow(self):
        with patch.object(settings, "ENABLE_CODE_NODE", False):
            result = await WorkflowExecutor().execute_workflow(GRAPH, {"value": 1})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["execution_trace"]), 3)


class _User:
    def __init__(self, active):
        self.is_active = active


class InactiveUserTests(IsolatedAsyncioTestCase):
    async def test_inactive_user_gets_403_not_401(self):
        with self.assertRaises(HTTPException) as ctx:
            await get_current_user(user=_User(False))
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_active_user_passes(self):
        u = _User(True)
        self.assertIs(await get_current_user(user=u), u)
