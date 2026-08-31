import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any
from app.tools.registry import ToolRegistry
from app.tools.discovery import DiscoveryRequest, DeterministicToolDiscovery
from app.tools.selector import LLMToolSelector, DeterministicToolSelector
from app.tools.models import ToolMetadata

@dataclass
class BenchmarkCase:
    name: str
    request: str
    required_tools: Set[str]
    optional_tools: Set[str] = field(default_factory=set)

@dataclass
class EvaluationResult:
    case_name: str
    request: str
    expected_required: Set[str]
    discovered: List[str]
    selected: List[str]
    missing_required_discovery: Set[str]
    missing_required_selection: Set[str]
    unnecessary_selected: Set[str]
    discovery_recall: float
    selection_recall: float
    selection_precision: float
    passed: bool
    failure_stage: Optional[str] = None

class Evaluator:
    def __init__(self, registry: ToolRegistry, use_llm_selector: bool = False, llm_mock_response: str = None):
        self.registry = registry
        self.discovery = DeterministicToolDiscovery()
        self.selector = DeterministicToolSelector()

    def set_selector(self, selector):
        self.selector = selector

    def evaluate_case(self, case: BenchmarkCase) -> EvaluationResult:
        # 1. Discovery
        req = DiscoveryRequest(query=case.request)
        discovery_result = self.discovery.discover(self.registry, req)
        discovered_names = [c.name for c in discovery_result.candidates]

        # 2. Selection
        selected_names = self.selector.select(case.request, discovery_result.candidates)
        
        # Metrics
        required = case.required_tools
        discovered_set = set(discovered_names)
        selected_set = set(selected_names)
        
        missing_discovery = required - discovered_set
        missing_selection = (required.intersection(discovered_set)) - selected_set
        unnecessary = selected_set - required - case.optional_tools
        
        discovery_recall = 1.0 if not required else len(required.intersection(discovered_set)) / len(required)
        selection_recall = 1.0 if not required else len(required.intersection(selected_set)) / len(required)
        selection_precision = 1.0 if not selected_set else len(selected_set.intersection(required.union(case.optional_tools))) / len(selected_set)
        
        passed = (missing_discovery == set() and missing_selection == set())
        
        failure_stage = None
        if not passed:
            if missing_discovery:
                failure_stage = "Discovery"
            elif missing_selection:
                failure_stage = "Selection"
                
        return EvaluationResult(
            case_name=case.name,
            request=case.request,
            expected_required=required,
            discovered=discovered_names,
            selected=selected_names,
            missing_required_discovery=missing_discovery,
            missing_required_selection=missing_selection,
            unnecessary_selected=unnecessary,
            discovery_recall=discovery_recall,
            selection_recall=selection_recall,
            selection_precision=selection_precision,
            passed=passed,
            failure_stage=failure_stage
        )

    def run_benchmark(self, cases: List[BenchmarkCase]) -> List[EvaluationResult]:
        return [self.evaluate_case(c) for c in cases]

def generate_report(results: List[EvaluationResult], total_tools: int) -> str:
    total_cases = len(results)
    passed_cases = sum(1 for r in results if r.passed)
    avg_discovery_recall = sum(r.discovery_recall for r in results) / total_cases if total_cases else 0
    avg_selection_recall = sum(r.selection_recall for r in results) / total_cases if total_cases else 0
    avg_selection_precision = sum(r.selection_precision for r in results) / total_cases if total_cases else 0
    avg_discovered_count = sum(len(r.discovered) for r in results) / total_cases if total_cases else 0
    avg_selected_count = sum(len(r.selected) for r in results) / total_cases if total_cases else 0

    failure_distribution = {"Discovery": 0, "Selection": 0}
    for r in results:
        if not r.passed and r.failure_stage:
            failure_distribution[r.failure_stage] = failure_distribution.get(r.failure_stage, 0) + 1

    report = f"""# A11_REPORT.md

## Tool Search Evaluation Suite

### Overview
This report details the evaluation of the Tool Search and Selection pipeline (Phase A11).
The benchmark measures discovery recall and selection quality without altering production behavior.

* Benchmark Size: {total_cases} cases
* Total Tools in Registry: {total_tools}
* Pass Rate: {passed_cases}/{total_cases} ({passed_cases/total_cases*100:.1f}%)

### Metrics
* Average Discovery Recall: {avg_discovery_recall*100:.1f}%
* Average Selection Recall: {avg_selection_recall*100:.1f}%
* Average Selection Precision: {avg_selection_precision*100:.1f}%
* Average Candidates Discovered: {avg_discovered_count:.1f}
* Average Tools Selected: {avg_selected_count:.1f}
* Overexposure Rate: {(avg_selected_count - (sum(len(r.expected_required) for r in results)/total_cases)):.1f} extra tools per request on average

### Failure Stage Distribution
* Discovery Failures: {failure_distribution.get("Discovery", 0)}
* Selection Failures: {failure_distribution.get("Selection", 0)}

### Baseline Comparison
* Registered Tools: {total_tools}
* Average Discovered: {avg_discovered_count:.1f}
* Average Selected: {avg_selected_count:.1f}

"""
    failures = [r for r in results if not r.passed]
    if failures:
        report += "### Representative Failures\\n"
        for r in failures[:5]:
            report += f"""
#### {r.case_name}
* **Request**: "{r.request}"
* **Expected**: {', '.join(r.expected_required) if r.expected_required else 'None'}
* **Discovered**: {len(r.discovered)} tools
* **Selected**: {', '.join(r.selected) if r.selected else 'None'}
* **Failure Stage**: {r.failure_stage}
* **Missing required**: {', '.join(r.missing_required_discovery.union(r.missing_required_selection))}
"""
    report += "### Limitations & Recommendations\\n"
    report += "This benchmark currently tests the deterministic fallback selector, as LLM invocations are not executed during this run. Results highlight where deterministic heuristics fail on ambiguous queries.\\n"
    return report

