"""Grounding pass: feed prose-checker findings back into generation via LLM correction.

E19 experiment: reduces C-hallucination (prose findings) without coverage cost.
"""

import json
import os
import subprocess
import sys
from typing import Dict, List


def run_grounding_pass(
    guides_dir: str,
    pkg_path: str,
    client,
    llm_cfg,
    max_findings_per_page: int = 20,
) -> Dict[str, int]:
    """Run the grounding pass over generated guide pages.

    Runs the prose API-semantics checker internally, then feeds findings
    back to the LLM for targeted correction per page.

    Args:
        guides_dir: Path to the generated guides directory.
        pkg_path: Path to the package source (for AST signatures).
        client: LLM client with .chat() method.
        llm_cfg: LLM config with max_tokens, temperature, etc.
        max_findings_per_page: Cap on findings sent to LLM per page.

    Returns:
        Dict with keys:
            findings_before: total prose findings before correction
            findings_after: total prose findings after correction
            pages_fixed: number of pages that were rewritten
    """
    # Run prose checker to get findings
    checker = os.path.join(os.path.dirname(__file__), "..", "eval", "prose_api_semantics_check.py")
    checker = os.path.normpath(checker)
    if not os.path.exists(checker):
        # Try alternate location
        checker = os.path.join(os.getcwd(), "eval", "prose_api_semantics_check.py")

    out_json = os.path.join(guides_dir, ".prose_check_grounding.json")
    try:
        result = subprocess.run(
            [sys.executable, checker, pkg_path, guides_dir, out_json],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"    grounding: prose checker failed: {result.stderr[:200]}")
            return {"findings_before": 0, "findings_after": 0, "pages_fixed": 0}
    except Exception as e:  # noqa: BLE001
        print(f"    grounding: prose checker error: {e}")
        return {"findings_before": 0, "findings_after": 0, "pages_fixed": 0}

    with open(out_json, "r", encoding="utf-8") as f:
        check_data = json.load(f)

    findings = check_data.get("findings", [])

    # Also run the semantic value checker (E20) and merge its findings
    sem_checker = os.path.join(os.path.dirname(__file__), "..", "eval", "semantic_value_check.py")
    sem_checker = os.path.normpath(sem_checker)
    if not os.path.exists(sem_checker):
        sem_checker = os.path.join(os.getcwd(), "eval", "semantic_value_check.py")
    sem_out_json = os.path.join(guides_dir, ".semantic_check_grounding.json")
    try:
        result = subprocess.run(
            [sys.executable, sem_checker, pkg_path, guides_dir, sem_out_json],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            with open(sem_out_json, "r", encoding="utf-8") as f:
                sem_data = json.load(f)
            sem_findings = sem_data.get("findings", [])
            findings.extend(sem_findings)
    except Exception as e:  # noqa: BLE001
        print(f"    grounding: semantic checker error: {e}")

    findings_before = len(findings)
    if not findings:
        # Clean up temp files
        for tmp in (out_json, sem_out_json):
            if os.path.exists(tmp):
                os.remove(tmp)
        return {"findings_before": 0, "findings_after": 0, "pages_fixed": 0}

    # Group findings by page
    by_page: Dict[str, List[dict]] = {}
    for f in findings:
        page = f.get("page", "unknown")
        by_page.setdefault(page, []).append(f)

    # Extract API surface for reference
    from repoquill.reference import extract_api_surface
    api_signatures = extract_api_surface(pkg_path)

    pages_fixed = 0
    for page, page_findings in by_page.items():
        if not page_findings:
            continue

        page_path = os.path.join(guides_dir, f"{page}.md")
        if not os.path.exists(page_path):
            continue

        # Cap findings to avoid overwhelming the LLM
        capped = page_findings[:max_findings_per_page]

        fixed = _fix_page_grounding(
            page_path=page_path,
            findings=capped,
            api_signatures=api_signatures,
            client=client,
            llm_cfg=llm_cfg,
        )
        if fixed:
            pages_fixed += 1

    # Re-run both checkers to get findings_after
    findings_after = 0
    try:
        result = subprocess.run(
            [sys.executable, checker, pkg_path, guides_dir, out_json],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            with open(out_json, "r", encoding="utf-8") as f:
                after_data = json.load(f)
            findings_after += len(after_data.get("findings", []))
    except Exception:  # noqa: BLE001
        pass
    try:
        result = subprocess.run(
            [sys.executable, sem_checker, pkg_path, guides_dir, sem_out_json],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            with open(sem_out_json, "r", encoding="utf-8") as f:
                sem_after = json.load(f)
            findings_after += len(sem_after.get("findings", []))
    except Exception:  # noqa: BLE001
        pass

    # Clean up temp files
    for tmp in (out_json, sem_out_json):
        if os.path.exists(tmp):
            os.remove(tmp)

    return {
        "findings_before": findings_before,
        "findings_after": findings_after,
        "pages_fixed": pages_fixed,
    }


def _fix_page_grounding(
    page_path: str,
    findings: List[dict],
    api_signatures: str,
    client,
    llm_cfg,
) -> bool:
    """Send a page + its prose findings to the LLM and ask it to fix them."""
    with open(page_path, "r", encoding="utf-8") as f:
        content = f.read()

    findings_lines = []
    for f in findings:
        ftype = f.get("type", "UNKNOWN")
        if ftype == "STRING_VALUE_MISMATCH":
            findings_lines.append(
                f"- [STRING_VALUE_MISMATCH] {f.get('call', 'N/A')}({f.get('param', 'N/A')}={f.get('doc_value', 'N/A')!r}) "
                f"but source default is {f.get('source_default', 'N/A')!r}. "
                f"Fix: change the value to match the source default."
            )
        elif ftype == "MISSING_CAVEAT":
            findings_lines.append(
                f"- [MISSING_CAVEAT] {f.get('method', 'N/A')}() raises an exception under "
                f"specific runtime conditions but the page doesn't mention it. "
                f"Caveat: {f.get('caveat', 'N/A')}. "
                f"Fix: add a brief note about this caveat near where the method is used."
            )
        else:
            # Prose checker finding types
            findings_lines.append(
                f"- [{ftype}] {f.get('name', 'N/A')} ({f.get('class', 'N/A')}): {f.get('detail', 'N/A')}\n"
                f"  Source truth: {f.get('source_truth', 'N/A')}\n"
                f"  Context: {f.get('context', 'N/A')}"
            )
    findings_text = "\n".join(findings_lines)

    prompt = f"""You are a documentation editor. The following page contains factual
errors about the API. Fix ONLY the specific errors listed below. Do not change
any other content, formatting, or structure.

## Findings to Fix
{findings_text}

## API Signatures (for reference)
{api_signatures}

## Page to Fix
<page>
{content}
</page>

INSTRUCTIONS:
- Fix ONLY the flagged claims. For each finding, correct the specific error
  described.
- If a finding is about a method being called as a property (or vice versa),
  change the syntax to match the source.
- If a finding is about a return type or argument type, correct the description
  to match the source signature.
- If a finding is STRING_VALUE_MISMATCH, change the string literal value in the
  code block to match the source default exactly.
- If a finding is MISSING_CAVEAT, add a brief one-line note (as a comment in the
  code block or a sentence in the prose) mentioning the caveat. Keep it concise.
- Do NOT add new sections or examples.
- Do NOT remove accurate content.
- Preserve all formatting, headings, and structure.
- Return ONLY the complete fixed markdown page, no preamble or explanation."""

    try:
        fixed = client.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=getattr(llm_cfg, "max_tokens", 8192),
            temperature=0.1,
        )
        from repoquill.llm import strip_code_fences
        fixed = strip_code_fences(fixed)
        if fixed.strip() and len(fixed) > 100:
            with open(page_path, "w", encoding="utf-8") as f:
                f.write(fixed)
            return True
    except Exception as e:  # noqa: BLE001
        print(f"    grounding fix failed for {os.path.basename(page_path)}: {e}")
    return False
