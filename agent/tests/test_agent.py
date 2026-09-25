# Copyright 2026 DataRobot, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest.mock import Mock, patch

import pytest
from langchain_core.prompts import ChatPromptTemplate

from agent import MyAgent
from agent.myagent import SYSTEM_PROMPT, graph_factory, prompt_template

EXPECTED_TOOLS = {
    "list_scenarios",
    "run_forecast",
    "compare_scenarios",
    "explain_forecast",
    "detect_forecast_issues",
    "apply_human_adjustment",
    "get_adjustment_log",
    "get_uncertainty_band",
    "get_backtest_result",
    "get_external_forecast",
    "generate_executive_summary",
}


@pytest.fixture(autouse=True)
def no_warmup():
    with patch("agent.tools.start_background_warmup"):
        yield


class TestMyAgentLangGraph:
    @pytest.fixture
    def agent(self) -> MyAgent:
        return MyAgent(llm=Mock(), verbose=True)

    def test_myagent_is_langgraph_agent_subclass(self):
        from datarobot_genai.langgraph.agent import LangGraphAgent

        assert issubclass(MyAgent, LangGraphAgent)

    def test_init_with_llm(self):
        mock_llm = Mock()
        agent = MyAgent(llm=mock_llm, verbose=True)
        assert agent.llm == mock_llm
        assert agent.verbose is True

    def test_prompt_template_uses_structured_history(self):
        """No {chat_history}: earlier tool calls (run_ids) are replayed as messages."""
        assert isinstance(prompt_template, ChatPromptTemplate)
        assert prompt_template.input_variables == ["topic"]
        messages = prompt_template.format_messages(topic="ベースシナリオを見せて")
        assert messages[-1].content == "ベースシナリオを見せて"

    def test_system_prompt_keeps_hilp_rules(self):
        assert "自分から補正を実行してはいけません" in SYSTEM_PROMPT
        assert "detect_forecast_issues" in SYSTEM_PROMPT
        assert "回答は日本語" in SYSTEM_PROMPT

    @patch("agent.myagent.create_agent")
    def test_graph_factory_single_forecast_node(self, mock_create_agent):
        graph = graph_factory(Mock(), [], verbose=False)
        assert "forecast_agent_node" in graph.nodes
        assert mock_create_agent.call_count == 1

    @patch("agent.myagent.create_agent")
    def test_graph_factory_passes_all_forecast_tools(self, mock_create_agent):
        mock_llm = Mock()
        extra_tool = Mock()
        extra_tool.name = "mcp_tool"
        graph_factory(mock_llm, [extra_tool], verbose=True)
        args, kwargs = mock_create_agent.call_args
        assert args[0] == mock_llm
        names = {t.name for t in kwargs["tools"]}
        assert EXPECTED_TOOLS <= names
        assert "mcp_tool" in names

    def test_workflow_property_uses_graph_factory(self, agent):
        with patch("agent.myagent.create_agent"):
            workflow = agent.workflow
            assert "forecast_agent_node" in workflow.nodes
