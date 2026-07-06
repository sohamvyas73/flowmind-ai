import sys
import types
import unittest
from unittest.mock import patch

google_genai = types.ModuleType("langchain_google_genai")
google_genai.ChatGoogleGenerativeAI = object
sys.modules["langchain_google_genai"] = google_genai

core_messages = types.ModuleType("langchain_core.messages")


class HumanMessage:
    def __init__(self, content=None):
        self.content = content


core_messages.HumanMessage = HumanMessage
sys.modules["langchain_core.messages"] = core_messages

from app.core.config import settings
from app.services.workflow_executor import NodeExecutor, WorkflowExecutor


class CodeRunnerSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.executor = NodeExecutor()
        self.workflow_executor = WorkflowExecutor()

    @patch.object(settings, "ENABLE_CODE_NODE", False)
    async def test_code_node_is_skipped_when_disabled(self):
        upstream = {"value": 42}

        result = await self.executor.execute_code_node(
            {"code": "output = 123"},
            {"current_node_id": "code_1", "previous_output": upstream},
        )

        self.assertTrue(result.get("skipped"))
        self.assertIn("disabled", result["reason"].lower())
        self.assertNotIn("error", result)
        self.assertEqual(result["output"], upstream)

    @patch.object(settings, "ENABLE_CODE_NODE", True)
    async def test_code_node_requires_explicit_feature_flag(self):
        result = await self.executor.execute_code_node(
            {"code": "output = input_data['value'] + 1", "timeout": 1},
            {"current_node_id": "code_1", "previous_output": {"value": 1}},
        )

        self.assertEqual(result["output"], 2)
        self.assertTrue(result["executed"])

    @patch.object(settings, "ENABLE_CODE_NODE", False)
    async def test_workflow_continues_when_code_node_is_disabled(self):
        graph_data = {
            "nodes": [
                {"id": "input_1", "type": "inputNode", "data": {"fields": [{"id": "f1", "name": "x", "type": "text"}]}},
                {"id": "code_1", "type": "codeNode", "data": {"code": "output = {'hacked': True}"}},
                {"id": "output_1", "type": "outputNode", "data": {"outputType": "json"}},
            ],
            "edges": [
                {"id": "e1", "source": "input_1", "target": "code_1"},
                {"id": "e2", "source": "code_1", "target": "output_1"},
            ],
        }

        result = await self.workflow_executor.execute_workflow(
            graph_data,
            {"node_inputs": {"input_1": {"x": "hello"}}},
        )

        self.assertEqual(result["status"], "completed")
        code_step = next(s for s in result["execution_trace"] if s["node_type"] == "codeNode")
        self.assertTrue(code_step["result"].get("skipped"))
        self.assertNotIn("error", code_step["result"])


if __name__ == "__main__":
    unittest.main()
