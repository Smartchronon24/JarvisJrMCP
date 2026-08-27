"""Small helpers for presenting terminal command results."""


def summarize_command_result(command: str, output: str, exit_code: int) -> str:
    """Return a compact, human-readable summary of a command result."""
    status = "succeeded" if exit_code == 0 else f"failed (exit code {exit_code})"
    output_text = " ".join(output.split())
    if not output_text:
        return f"{command}: {status}; no output"
    return f"{command}: {status}; {output_text}"
