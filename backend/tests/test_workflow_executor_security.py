import sys
import types
import unittest

from app.core.config import settings

google_genai = types.ModuleType("langchain_google_genai")
google_genai.ChatGoogleGenerativeAI = object
sys.modules.setdefault("langchain_google_genai", google_genai)

core_messages = types.ModuleType("langchain_core.messages")


class HumanMessage:
    def __init__(self, content=None):
        self.content = content


core_messages.HumanMessage = HumanMessage
sys.modules.setdefault("langchain_core.messages", core_messages)

from app.services.workflow_executor import NodeExecutor


class CodeRunnerSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._original_enable_code_node = settings.ENABLE_CODE_NODE
        self.executor = NodeExecutor()

    async def asyncTearDown(self):
        settings.ENABLE_CODE_NODE = self._original_enable_code_node

    async def test_code_node_is_disabled_by_default(self):
        settings.ENABLE_CODE_NODE = False

        result = await self.executor.execute_code_node(
            {"code": "output = 123"},
            {"current_node_id": "code_1", "previous_output": {"value": 1}},
        )

        self.assertIn("error", result)
        self.assertIn("disabled", result["error"].lower())
        self.assertNotIn("output", result)
        self.assertNotIn("executed", result)

    async def test_code_node_requires_explicit_feature_flag(self):
        settings.ENABLE_CODE_NODE = True

        result = await self.executor.execute_code_node(
            {"code": "output = input_data['value'] + 1", "timeout": 1},
            {"current_node_id": "code_1", "previous_output": {"value": 1}},
        )

        self.assertEqual(result["output"], 2)
        self.assertTrue(result["executed"])


if __name__ == "__main__":
    unittest.main()
