#!/usr/bin/env python3
"""
B17-A: Control Experiment — Compare Claude execution paths

This test harness establishes the exact parameters used by:
1. Direct Claude CLI
2. Jarvis runtime (simulated)
3. Claudex Studio (runtime inspection)

For the prompt: "hi"
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(message)s',
    stream=sys.stdout,
)

# Add app to path
app_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_root))

from app.runtime.server import RuntimeServer, FrameworkResolver
from app.runtime.contract import RuntimeConfig
from app.runtime.adapters.claude import ClaudeAdapter


@dataclass
class CommandProfile:
    """Captured command execution profile."""
    name: str
    prompt: str
    command: list[str]
    cwd: str
    env_keys: list[str]
    anthropic_env: dict
    mcp_config: Optional[str]
    interactive: bool
    stdin_mode: str


class B17ControlExperiment:
    """Establish control conditions for contamination investigation."""
    
    TEST_PROMPT = "hi"
    
    @staticmethod
    def hash_value(value: str) -> str:
        """Hash sensitive values for logging."""
        return hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]
    
    @staticmethod
    def profile_direct_cli() -> CommandProfile:
        """Profile 1: Direct Claude CLI invocation."""
        print("\n" + "=" * 80)
        print("TEST PROFILE 1: Direct Claude CLI")
        print("=" * 80)
        
        cmd = ["claude", "--model", "gpt-oss:120b-cloud", "--print", B17ControlExperiment.TEST_PROMPT]
        
        # Simulate environment a user would set
        env = os.environ.copy()
        anthropic_env = {}
        for k, v in env.items():
            if "ANTHROPIC" in k or "CLAUDE" in k or "OLLAMA" in k:
                redacted = "<REDACTED>" if "TOKEN" in k or "KEY" in k else v
                anthropic_env[k] = redacted
        
        print(f"Command: {' '.join(cmd)}")
        print(f"Working directory: {os.getcwd()}")
        print(f"Prompt: '{B17ControlExperiment.TEST_PROMPT}'")
        print(f"Prompt hash: {hashlib.sha256(B17ControlExperiment.TEST_PROMPT.encode()).hexdigest()[:8]}")
        print(f"stdin mode: DEVNULL (non-interactive)")
        print(f"Environment (Anthropic-related):")
        for k, v in sorted(anthropic_env.items()):
            print(f"  {k}={v}")
        
        return CommandProfile(
            name="Direct CLI",
            prompt=B17ControlExperiment.TEST_PROMPT,
            command=cmd,
            cwd=os.getcwd(),
            env_keys=sorted(env.keys()),
            anthropic_env=anthropic_env,
            mcp_config=None,
            interactive=False,
            stdin_mode="DEVNULL"
        )
    
    @staticmethod
    async def profile_jarvis_runtime() -> CommandProfile:
        """Profile 2: Jarvis runtime (without Claudex frontend)."""
        print("\n" + "=" * 80)
        print("TEST PROFILE 2: Jarvis Runtime (Direct)")
        print("=" * 80)
        
        # Create the exact RuntimeConfig that Claudex would create
        config = RuntimeConfig(
            executable_path="claude",
            prompt=B17ControlExperiment.TEST_PROMPT,
            model_name="gpt-oss:120b-cloud",
            provider_name="ollama",
            endpoint_url=None,
            working_directory=os.getcwd(),
            environment={},
            interactive=False,
            extra={},
        )
        
        # Build command as adapter would
        adapter = ClaudeAdapter()
        cmd = adapter.build_command(config)
        env = adapter.build_environment(config)
        
        # Merge with parent environment
        merged_env = os.environ.copy()
        merged_env.update(env)
        
        anthropic_env = {}
        for k, v in merged_env.items():
            if "ANTHROPIC" in k or "CLAUDE" in k or "OLLAMA" in k:
                redacted = "<REDACTED>" if "TOKEN" in k or "KEY" in k else v
                anthropic_env[k] = redacted
        
        print(f"Command: {' '.join(cmd)}")
        print(f"Working directory: {config.working_directory}")
        print(f"Prompt: '{config.prompt}'")
        print(f"Prompt hash: {hashlib.sha256(config.prompt.encode()).hexdigest()[:8]}")
        print(f"stdin mode: DEVNULL (non-interactive)")
        print(f"Environment (Anthropic-related):")
        for k, v in sorted(anthropic_env.items()):
            print(f"  {k}={v}")
        print(f"MCP config: {config.extra.get('jarvis_mcp_config', 'None')}")
        
        return CommandProfile(
            name="Jarvis Runtime",
            prompt=config.prompt,
            command=cmd,
            cwd=config.working_directory,
            env_keys=sorted(merged_env.keys()),
            anthropic_env=anthropic_env,
            mcp_config=config.extra.get('jarvis_mcp_config'),
            interactive=config.interactive,
            stdin_mode="DEVNULL"
        )
    
    @staticmethod
    def compare_profiles(p1: CommandProfile, p2: CommandProfile) -> None:
        """Compare two command profiles."""
        print("\n" + "=" * 80)
        print(f"COMPARISON: {p1.name} vs {p2.name}")
        print("=" * 80)
        
        # Compare prompts
        print(f"\nPrompt comparison:")
        print(f"  {p1.name}: '{p1.prompt}'")
        print(f"  {p2.name}: '{p2.prompt}'")
        if p1.prompt == p2.prompt:
            print(f"  [OK] IDENTICAL")
        else:
            print(f"  [FAIL] DIFFERENT")
        
        # Compare commands
        print(f"\nCommand comparison:")
        print(f"  {p1.name}: {' '.join(p1.command)}")
        print(f"  {p2.name}: {' '.join(p2.command)}")
        if p1.command == p2.command:
            print(f"  [OK] IDENTICAL")
        else:
            print(f"  [FAIL] DIFFERENT")
            for i, (arg1, arg2) in enumerate(zip(p1.command, p2.command)):
                if arg1 != arg2:
                    print(f"    Arg {i}: '{arg1}' vs '{arg2}'")
        
        # Compare working directories
        print(f"\nWorking directory comparison:")
        print(f"  {p1.name}: {p1.cwd}")
        print(f"  {p2.name}: {p2.cwd}")
        if p1.cwd == p2.cwd:
            print(f"  [OK] IDENTICAL")
        else:
            print(f"  [FAIL] DIFFERENT")
        
        # Compare Anthropic environment
        print(f"\nAnthropic environment comparison:")
        all_keys = set(p1.anthropic_env.keys()) | set(p2.anthropic_env.keys())
        for key in sorted(all_keys):
            v1 = p1.anthropic_env.get(key, "<NOT SET>")
            v2 = p2.anthropic_env.get(key, "<NOT SET>")
            if v1 == v2:
                print(f"  [OK] {key}: {v1}")
            else:
                print(f"  [FAIL] {key}: {v1} vs {v2}")
    
    @staticmethod
    async def run_experiment() -> None:
        """Run the complete control experiment."""
        print("\n" + "*" * 80)
        print("B17-A: CONTROL EXPERIMENT")
        print("*" * 80)
        print("\nComparing Claude execution paths for prompt: 'hi'")
        print("This establishes the baseline for investigating contamination.\n")
        
        # Profile 1: Direct CLI
        p1 = B17ControlExperiment.profile_direct_cli()
        
        # Profile 2: Jarvis runtime
        p2 = await B17ControlExperiment.profile_jarvis_runtime()
        
        # Compare
        B17ControlExperiment.compare_profiles(p1, p2)
        
        # Summary
        print("\n" + "*" * 80)
        print("CONTROL EXPERIMENT SUMMARY")
        print("*" * 80)
        
        identical_prompt = p1.prompt == p2.prompt
        identical_command = p1.command == p2.command
        identical_cwd = p1.cwd == p2.cwd
        identical_env = p1.anthropic_env == p2.anthropic_env
        
        print(f"\nPrompt integrity:       {'PASS' if identical_prompt else 'FAIL'}")
        print(f"Command construction:   {'PASS' if identical_command else 'FAIL'}")
        print(f"Working directory:      {'PASS' if identical_cwd else 'FAIL'}")
        print(f"Environment setup:      {'PASS' if identical_env else 'FAIL'}")
        
        if all([identical_prompt, identical_command, identical_cwd, identical_env]):
            print("\n[OK] Baseline established: Direct CLI and Jarvis runtime produce identical execution parameters.")
            print("  Any differences in behavior must come from Claudex Studio, MCP configuration,")
            print("  or Claude Code session/internal behavior.")
        else:
            print("\n[FAIL] Differences detected between Direct CLI and Jarvis runtime.")
            print("  These differences could explain contamination behavior.")
        
        print("\nNext: B17-B (Hidden prompt/context injection), B17-C (Session reuse)")


async def main():
    """Run B17-A investigation."""
    exp = B17ControlExperiment()
    await exp.run_experiment()


if __name__ == "__main__":
    asyncio.run(main())
