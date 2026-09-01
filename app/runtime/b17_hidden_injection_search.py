#!/usr/bin/env python3
"""
B17-B: Hidden Prompt/Context Injection Investigation

Search the entire codebase for anything capable of:
1. Appending system prompts
2. Injecting hidden instructions
3. Reusing sessions
4. Loading previous conversation context
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple


class B17PromptInjectionInvestigation:
    """Investigate potential hidden prompt/context injection."""
    
    # Keywords to search for that might indicate hidden injection
    INJECTION_KEYWORDS = [
        # System prompt related
        "append-system-prompt",
        "system-prompt",
        "system_prompt",
        "append_system_prompt",
        
        # Prompt/context related
        "user_prompt",
        "user-prompt",
        "conversation",
        "history",
        "messages",
        "context",
        
        # Session/resume related
        "session",
        "session-id",
        "session_id",
        "resume",
        "continue",
        "continuation",
        
        # Title/summary generation
        "generate_session_title",
        "generate-session-title",
        "session_title",
        "session-title",
        "title",
        "summary",
        
        # Security/review related (suspiciously present)
        "security",
        "review",
        "audit",
        "code-review",
        "code_review",
        "security-review",
        "security_review",
        
        # Instruction/task related
        "instructions",
        "instruction",
        "task",
        "briefing",
        "brief",
        
        # Skill/tool related
        "skill",
        "tool",
        "capability",
        "permission",
        "approval",
        
        # Config files
        "claude.md",
        "CLAUDE.md",
        "agents.md",
        "AGENTS.md",
        "settings.json",
        ".claude",
    ]
    
    # File paths to specifically inspect
    CRITICAL_PATHS = [
        "app/runtime",
        "claudex-studio",
        "app/tools",
        "app/mcp",
        "Implementation_Reports",
    ]
    
    # File patterns to exclude
    EXCLUDE_PATTERNS = [
        r"\.pyc",
        r"__pycache__",
        r"\.git",
        r"node_modules",
        r"\.DS_Store",
        r"test_b1[567]",  # Exclude test reports
        r"\.md$",  # Exclude markdown for now
    ]
    
    @staticmethod
    def should_skip_file(path: Path) -> bool:
        """Check if file should be skipped."""
        path_str = str(path).lower()
        for pattern in B17PromptInjectionInvestigation.EXCLUDE_PATTERNS:
            if re.search(pattern, path_str):
                return True
        return False
    
    @staticmethod
    def search_files_for_keyword(keyword: str, root: Path = Path(".")) -> List[Tuple[Path, int, str]]:
        """Search files for a keyword and return matching lines."""
        matches = []
        
        try:
            for critical_path in B17PromptInjectionInvestigation.CRITICAL_PATHS:
                search_root = root / critical_path
                if not search_root.exists():
                    continue
                
                for file_path in search_root.rglob("*"):
                    if file_path.is_file() and not B17PromptInjectionInvestigation.should_skip_file(file_path):
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                for line_no, line in enumerate(f, 1):
                                    if keyword.lower() in line.lower():
                                        matches.append((file_path, line_no, line.strip()))
                        except Exception:
                            pass
        except Exception:
            pass
        
        return matches
    
    @staticmethod
    def run_investigation():
        """Run the complete hidden injection investigation."""
        print("\n" + "*" * 80)
        print("B17-B: HIDDEN PROMPT/CONTEXT INJECTION INVESTIGATION")
        print("*" * 80)
        print("\nSearching for capability to inject hidden system prompts, context, or instructions...\n")
        
        root = Path(".")
        all_findings = {}
        
        # Search for each keyword
        for keyword in B17PromptInjectionInvestigation.INJECTION_KEYWORDS:
            matches = B17PromptInjectionInvestigation.search_files_for_keyword(keyword, root)
            if matches:
                all_findings[keyword] = matches
        
        if not all_findings:
            print("[OK] No potential hidden injection keywords found in critical paths.")
            print("\nConclusion: No obvious prompt injection capability detected in code.")
            return
        
        # Print findings grouped by category
        categories = {
            "SYSTEM_PROMPT": ["append-system-prompt", "system-prompt", "system_prompt", "append_system_prompt"],
            "CONTEXT_INJECTION": ["conversation", "history", "messages", "context", "user_prompt", "user-prompt"],
            "SESSION_REUSE": ["session", "session-id", "session_id", "resume", "continue", "continuation"],
            "TITLE_GENERATION": ["generate_session_title", "generate-session-title", "session_title", "session-title", "title", "summary"],
            "SECURITY_REVIEW": ["security", "review", "audit", "code-review", "code_review", "security-review", "security_review"],
            "INSTRUCTION_INJECTION": ["instructions", "instruction", "task", "briefing", "brief"],
            "CONFIGURATION": ["claude.md", "CLAUDE.md", "agents.md", "AGENTS.md", "settings.json", ".claude"],
        }
        
        print("=" * 80)
        print("FINDINGS BY CATEGORY")
        print("=" * 80)
        
        for category, keywords in categories.items():
            category_findings = {}
            for keyword in keywords:
                if keyword in all_findings:
                    category_findings[keyword] = all_findings[keyword]
            
            if category_findings:
                print(f"\n{category}:")
                for keyword, matches in sorted(category_findings.items()):
                    print(f"  [{len(matches)} matches] '{keyword}':")
                    # Show first few matches
                    for path, line_no, line in matches[:3]:
                        print(f"    {path}:{line_no}: {line[:70]}")
                    if len(matches) > 3:
                        print(f"    ... and {len(matches) - 3} more matches")
        
        # Analyze suspicious findings
        print("\n" + "=" * 80)
        print("SUSPICIOUS PATTERNS ANALYSIS")
        print("=" * 80)
        
        # Check for session_title/title generation
        if "generate_session_title" in all_findings or "session_title" in all_findings:
            print("\n[ATTENTION] Session title generation detected.")
            print("  This could trigger background Claude requests.")
            for keyword in ["generate_session_title", "session_title"]:
                if keyword in all_findings:
                    for path, line_no, line in all_findings[keyword][:2]:
                        print(f"    {path}:{line_no}")
        
        # Check for security review keywords
        security_keywords = ["security", "review", "audit", "code-review", "code_review", "security-review", "security_review"]
        security_matches = []
        for kw in security_keywords:
            if kw in all_findings:
                security_matches.extend(all_findings[kw])
        
        if security_matches:
            print(f"\n[ATTENTION] Security/review keywords found ({len(security_matches)} total).")
            print("  Filtering for actual security-review functionality:")
            for path, line_no, line in security_matches:
                # Filter for actual implementation, not just comments
                if "security" in line.lower() and ("review" in line.lower() or "audit" in line.lower()):
                    if not line.strip().startswith("#"):
                        print(f"    {path}:{line_no}: {line[:70]}")
        
        # Check for resume/continue flags
        resume_keywords = ["resume", "continue", "--resume", "--continue"]
        for kw in resume_keywords:
            if kw in all_findings:
                print(f"\n[ATTENTION] '{kw}' detected.")
                for path, line_no, line in all_findings[kw][:2]:
                    print(f"  {path}:{line_no}: {line[:70]}")
        
        print("\n" + "=" * 80)
        print("REQUIRED FILES TO INSPECT")
        print("=" * 80)
        print("\nPlease manually inspect these files for hidden prompt injection:")
        print("  1. .claude/ (user-level Claude configuration)")
        print("  2. CLAUDE.md (project-level Claude instructions)")
        print("  3. AGENTS.md (agent definitions)")
        print("  4. app/runtime/server.py (request handling)")
        print("  5. app/runtime/adapters/claude.py (command building)")
        print("  6. claudex-studio/app.js (frontend state)")
        print("  7. claudex-studio/websocket-client.js (WebSocket payload)")


if __name__ == "__main__":
    investigation = B17PromptInjectionInvestigation()
    investigation.run_investigation()
