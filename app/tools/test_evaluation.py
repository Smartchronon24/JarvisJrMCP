from typing import List
from app.tools.evaluation import BenchmarkCase, Evaluator, EvaluationResult
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.discovery import DiscoveryRequest

def test_evaluation_success_case():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(
        name="test__success_tool",
        server="test",
        tool_name="success_tool",
        capability="general",
        description="A tool that succeeds",
        input_schema={}
    ))
    evaluator = Evaluator(reg)
    case = BenchmarkCase(
        name="Test Success",
        request="success_tool",
        required_tools={"test__success_tool"}
    )
    result = evaluator.evaluate_case(case)
    assert result.passed is True
    assert result.failure_stage is None
    assert result.discovery_recall == 1.0
    assert result.selection_recall == 1.0

def test_evaluation_discovery_failure():
    reg = ToolRegistry()
    evaluator = Evaluator(reg)
    case = BenchmarkCase(
        name="Test Discovery Failure",
        request="find me something",
        required_tools={"missing__tool"}
    )
    result = evaluator.evaluate_case(case)
    assert result.passed is False
    assert result.failure_stage == "Discovery"
    assert "missing__tool" in result.missing_required_discovery
    assert result.discovery_recall == 0.0

def test_evaluation_selection_failure():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(
        name="test__find",
        server="test",
        tool_name="find",
        capability="general",
        description="find something",
        input_schema={}
    ))
    
    class MockSelector:
        def select(self, request, candidates, max_tools=None, runtime_state=None):
            return [] # Fail to select the tool

    evaluator = Evaluator(reg)
    evaluator.set_selector(MockSelector())
    
    case = BenchmarkCase(
        name="Test Selection Failure",
        request="find something",
        required_tools={"test__find"}
    )
    result = evaluator.evaluate_case(case)
    assert result.passed is False
    assert result.failure_stage == "Selection"
    assert "test__find" in result.missing_required_selection
    assert result.selection_recall == 0.0

def test_evaluation_no_tool_case():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(
        name="test__irrelevant",
        server="test",
        tool_name="irrelevant",
        capability="general",
        description="irrelevant",
        input_schema={}
    ))
    evaluator = Evaluator(reg)
    
    case = BenchmarkCase(
        name="No Tool",
        request="What is the capital of France?",
        required_tools=set()
    )
    result = evaluator.evaluate_case(case)
    assert result.passed is True
    assert len(result.discovered) == 0
    assert len(result.selected) == 0
    assert result.discovery_recall == 1.0
    assert result.selection_recall == 1.0

def test_evaluation_multi_tool():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(
        name="test__tool_a", server="test", tool_name="tool_a", capability="general", description="tool a", input_schema={}
    ))
    reg.register_tool(ToolMetadata(
        name="test__tool_b", server="test", tool_name="tool_b", capability="general", description="tool b", input_schema={}
    ))
    
    class MockSelector:
        def select(self, request, candidates, max_tools=None, runtime_state=None):
            return ["test__tool_a", "test__tool_b"]

    evaluator = Evaluator(reg)
    evaluator.set_selector(MockSelector())
    
    case = BenchmarkCase(
        name="Multi Tool",
        request="tool_a and tool_b",
        required_tools={"test__tool_a", "test__tool_b"}
    )
    result = evaluator.evaluate_case(case)
    assert result.passed is True
    assert result.discovery_recall == 1.0
    assert result.selection_recall == 1.0
