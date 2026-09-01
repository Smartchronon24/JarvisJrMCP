"""
B16: Prompt Integrity Diagnostic Test

Traces a simple prompt through the entire system to detect mutations,
duplications, or hidden injections.
"""

import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Setup logging to capture all B16 diagnostics
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s | %(levelname)s | %(message)s',
    stream=sys.stdout,
)

# Add app to path
app_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_root))

from app.runtime.server import RuntimeServer, FrameworkResolver
from app.runtime.contract import RuntimeConfig, FrameworkIdentity
from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.executor import RuntimeProcessExecutor


class B16DiagnosticTest:
    """Comprehensive prompt integrity diagnostic."""

    @staticmethod
    def compute_prompt_hash(prompt: str) -> str:
        """Compute SHA-256 hash of prompt for integrity verification."""
        return hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    async def test_simple_hi_prompt():
        """Test 1: Trace a simple 'Hi' prompt through the entire system."""
        test_prompt = "Hi"
        expected_hash = B16DiagnosticTest.compute_prompt_hash(test_prompt)
        
        print("\n" + "=" * 80)
        print("B16-T1: Simple 'Hi' Prompt Integrity Test")
        print("=" * 80)
        print(f"Input prompt: '{test_prompt}'")
        print(f"Expected hash: {expected_hash}")
        print()
        
        server = RuntimeServer()
        
        # Mock the process executor to prevent actual subprocess
        with patch('app.runtime.server.RuntimeProcessExecutor.execute') as mock_execute:
            # Create a mock process
            mock_process = AsyncMock()
            mock_process.pid = 99999
            mock_execute.return_value = mock_process
            
            # Call create_session with the test prompt
            try:
                orchestrator, run_id = await server.create_session(
                    framework='claude',
                    prompt=test_prompt,
                    model='gpt-oss:120b-cloud',
                    provider='ollama',
                )
                
                print(f"Session created: {run_id}")
                print(f"Orchestrator prompt: '{orchestrator.config.prompt}'")
                computed_hash = B16DiagnosticTest.compute_prompt_hash(orchestrator.config.prompt or "")
                print(f"Config hash: {computed_hash}")
                
                # Verify hash matches
                assert computed_hash == expected_hash, f"Prompt mutated! Expected {expected_hash}, got {computed_hash}"
                print(">>> PASS: Prompt integrity maintained at server boundary")
                
            except Exception as exc:
                print(f"✗ FAIL: {exc}")
                raise
            finally:
                await server.shutdown()

    @staticmethod
    async def test_complex_prompt():
        """Test 2: Trace a complex prompt through the system."""
        test_prompt = "could you check recent unread whatsapp messages? donot do anything else."
        expected_hash = B16DiagnosticTest.compute_prompt_hash(test_prompt)
        
        print("\n" + "=" * 80)
        print("B16-T2: Complex Prompt Integrity Test")
        print("=" * 80)
        print(f"Input prompt: '{test_prompt}'")
        print(f"Expected hash: {expected_hash}")
        print()
        
        server = RuntimeServer()
        
        with patch('app.runtime.server.RuntimeProcessExecutor.execute') as mock_execute:
            mock_process = AsyncMock()
            mock_process.pid = 99998
            mock_execute.return_value = mock_process
            
            try:
                orchestrator, run_id = await server.create_session(
                    framework='claude',
                    prompt=test_prompt,
                    model='gpt-oss:120b-cloud',
                    provider='ollama',
                )
                
                print(f"Session created: {run_id}")
                print(f"Orchestrator prompt: '{orchestrator.config.prompt}'")
                computed_hash = B16DiagnosticTest.compute_prompt_hash(orchestrator.config.prompt or "")
                print(f"Config hash: {computed_hash}")
                
                assert computed_hash == expected_hash, f"Prompt mutated! Expected {expected_hash}, got {computed_hash}"
                print("✓ PASS: Complex prompt integrity maintained")
                
            except Exception as exc:
                print(f"✗ FAIL: {exc}")
                raise
            finally:
                await server.shutdown()

    @staticmethod
    def test_adapter_command_building():
        """Test 3: Verify Claude adapter builds correct commands without mutation."""
        print("\n" + "=" * 80)
        print("B16-T3: Claude Adapter Command Building Test")
        print("=" * 80)
        
        test_prompt = "Hi"
        adapter = ClaudeAdapter()
        
        config = RuntimeConfig(
            executable_path="claude",
            prompt=test_prompt,
            model_name="gpt-oss:120b-cloud",
            provider_name="ollama",
            endpoint_url="http://localhost:11434",
            interactive=False,
        )
        
        cmd = adapter.build_command(config)
        print(f"Input prompt: '{test_prompt}'")
        print(f"Generated command: {cmd}")
        
        # Verify prompt is last argument
        assert cmd[-1] == test_prompt, f"Prompt not preserved in command! Last arg: {cmd[-1]}"
        print("✓ PASS: Prompt preserved as final CLI argument")
        
        # Verify no extra system prompts injected
        assert "--append-system-prompt" not in cmd
        assert "--system-prompt" not in cmd
        assert "security" not in str(cmd).lower()
        assert "review" not in str(cmd).lower()
        print("✓ PASS: No hidden system prompts injected")

    @staticmethod
    def test_adapter_environment_setup():
        """Test 4: Verify adapter doesn't inject unexpected environment."""
        print("\n" + "=" * 80)
        print("B16-T4: Claude Adapter Environment Setup Test")
        print("=" * 80)
        
        adapter = ClaudeAdapter()
        
        config = RuntimeConfig(
            executable_path="claude",
            prompt="Hi",
            model_name="gpt-oss:120b-cloud",
            provider_name="ollama",
            endpoint_url="http://localhost:11434",
            environment={},
        )
        
        env = adapter.build_environment(config)
        
        print(f"Generated environment keys: {sorted(env.keys())}")
        
        # Verify expected keys are present
        expected_keys = {"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"}
        for key in expected_keys:
            assert key in env, f"Missing expected env var: {key}"
        
        # Verify no prompt-related keys
        for key in env.keys():
            assert "PROMPT" not in key, f"Unexpected prompt-related env var: {key}"
            assert "SECURITY" not in key, f"Unexpected security-related env var: {key}"
            assert "REVIEW" not in key, f"Unexpected review-related env var: {key}"
        
        print("✓ PASS: Environment setup contains only expected variables")

    @staticmethod
    async def test_multiple_sequential_requests():
        """Test 5: Verify sequential requests don't contaminate each other."""
        print("\n" + "=" * 80)
        print("B16-T5: Sequential Request Contamination Test")
        print("=" * 80)
        
        test_prompts = [
            "Hi",
            "What is 2 + 2?",
            "Repeat exactly: HELLO_TEST_123",
        ]
        
        server = RuntimeServer()
        hashes = {}
        
        with patch('app.runtime.server.RuntimeProcessExecutor.execute') as mock_execute:
            for i, test_prompt in enumerate(test_prompts):
                mock_process = AsyncMock()
                mock_process.pid = 90000 + i
                mock_execute.return_value = mock_process
                
                try:
                    orchestrator, run_id = await server.create_session(
                        framework='claude',
                        prompt=test_prompt,
                    )
                    
                    prompt_hash = B16DiagnosticTest.compute_prompt_hash(test_prompt)
                    config_hash = B16DiagnosticTest.compute_prompt_hash(orchestrator.config.prompt or "")
                    
                    print(f"\nRequest {i + 1}: '{test_prompt}'")
                    print(f"  Expected hash: {prompt_hash}")
                    print(f"  Config hash:   {config_hash}")
                    
                    assert prompt_hash == config_hash, f"Prompt mutated in request {i + 1}!"
                    hashes[test_prompt] = prompt_hash
                    print(f"  ✓ PASS")
                    
                except Exception as exc:
                    print(f"  ✗ FAIL: {exc}")
                    raise
            
            # Verify all hashes are unique (no contamination)
            unique_hashes = len(set(hashes.values()))
            assert unique_hashes == len(hashes), "Detected contamination: multiple prompts produced same hash!"
            print(f"\n✓ PASS: All {len(hashes)} requests maintained unique, unchanged prompts")
        
        await server.shutdown()

    @staticmethod
    async def run_all_tests():
        """Execute all B16 diagnostic tests."""
        print("\n" + "*" * 80)
        print("B16: PROMPT INTEGRITY & SESSION CONTAMINATION DIAGNOSTIC")
        print("*" * 80)
        
        tests = [
            ("Simple 'Hi' Prompt", B16DiagnosticTest.test_simple_hi_prompt),
            ("Complex Prompt", B16DiagnosticTest.test_complex_prompt),
            ("Adapter Command Building", B16DiagnosticTest.test_adapter_command_building),
            ("Adapter Environment Setup", B16DiagnosticTest.test_adapter_environment_setup),
            ("Sequential Requests", B16DiagnosticTest.test_multiple_sequential_requests),
        ]
        
        passed = 0
        failed = 0
        
        for name, test_func in tests:
            try:
                if asyncio.iscoroutinefunction(test_func):
                    await test_func()
                else:
                    test_func()
                passed += 1
                print(f"\n[PASS] {name}")
            except AssertionError as exc:
                failed += 1
                print(f"\n[FAIL] {name}")
                print(f"  Error: {exc}")
            except Exception as exc:
                failed += 1
                print(f"\n[ERROR] {name}")
                print(f"  Error: {exc}")
        
        print("\n" + "*" * 80)
        print(f"SUMMARY: {passed} passed, {failed} failed")
        print("*" * 80)
        
        return failed == 0


async def main():
    success = await B16DiagnosticTest.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
