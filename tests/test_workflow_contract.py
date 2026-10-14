"""Static contract tests for the GitHub Actions workflow YAML files.

These tests enforce the P0-5 safety contract without any network access:
parse the workflow YAMLs and assert input backward compatibility, the
validate/publish job split, minimal permissions, and concurrency groups.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

REUSABLE = "reusable.yml"
DOCS = "docs.yml"
PUBLISH = "publish.yml"


def _load(name: str) -> dict:
    with (WORKFLOWS / name).open() as f:
        wf = yaml.safe_load(f)
    assert isinstance(wf, dict), f"{name} did not parse to a mapping"
    assert isinstance(wf.get("jobs"), dict) and wf["jobs"], f"{name} has no jobs"
    return wf


def _on(wf: dict) -> dict:
    # PyYAML parses the unquoted `on:` key as boolean True.
    return wf.get("on", wf.get(True))


def _inputs(wf: dict) -> dict:
    return _on(wf)["workflow_call"]["inputs"]


def _run_steps(job: dict) -> list:
    return [step.get("run", "") for step in job.get("steps", [])]


# Legacy workflow_call inputs that must keep their exact names/defaults.
LEGACY_INPUTS = {
    "config": "repoquill.yml",
    "api_key_secret": "LLM_API_KEY",
    "api_key_env": "OPENAI_API_KEY",
    "no_llm": "false",
    "python_version": "3.11",
    "install_rag": "false",
    "deploy_branch": "",
    "deploy_path": "site",
    "clean": "false",
}


def test_all_workflows_parse():
    for name in (REUSABLE, DOCS, PUBLISH):
        wf = _load(name)
        assert isinstance(_on(wf), dict), f"{name} has no trigger block"


def test_reusable_legacy_inputs_preserved():
    inputs = _inputs(_load(REUSABLE))
    for name, default in LEGACY_INPUTS.items():
        assert name in inputs, f"missing legacy input {name!r}"
        spec = inputs[name]
        assert spec.get("type") == "string", f"{name}: type changed"
        assert spec.get("required") is False, f"{name}: became required"
        assert spec.get("default") == default, f"{name}: default changed"


def test_reusable_llm_secret_declared():
    secrets = _on(_load(REUSABLE))["workflow_call"]["secrets"]
    assert "LLM_API_KEY" in secrets


def test_reusable_publish_input_default_true():
    spec = _inputs(_load(REUSABLE))["publish"]
    assert spec.get("type") == "string"
    assert spec.get("required") is False
    assert spec.get("default") == "true"


def test_validate_job_exists_and_is_read_only():
    job = _load(REUSABLE)["jobs"]["validate"]
    assert job["permissions"].get("contents") == "read"


def test_validate_job_never_commits_or_pushes():
    for run in _run_steps(_load(REUSABLE)["jobs"]["validate"]):
        assert "git push" not in run, "validate job must not push"
        assert "git commit" not in run, "validate job must not commit"


def test_publish_job_needs_validate_and_is_writable():
    job = _load(REUSABLE)["jobs"]["publish"]
    assert "validate" in job.get("needs", [])
    assert job["permissions"].get("contents") == "write"


def test_publish_job_excludes_pr_contexts():
    cond = _load(REUSABLE)["jobs"]["publish"].get("if", "")
    assert "inputs.publish == 'true'" in cond
    assert "github.event_name != 'pull_request'" in cond
    assert "github.event_name != 'pull_request_target'" in cond


def test_publish_and_deploy_jobs_have_no_llm_secret():
    wf = _load(REUSABLE)
    for job_name in ("publish", "deploy"):
        blob = yaml.dump(wf["jobs"][job_name])
        assert "LLM_API_KEY" not in blob, f"{job_name} job references the LLM secret"


def test_deploy_job_uses_github_token_only():
    blob = yaml.dump(_load(REUSABLE)["jobs"]["deploy"])
    assert "secrets.GITHUB_TOKEN" in blob


def test_deploy_job_needs_publish_and_is_gated():
    job = _load(REUSABLE)["jobs"]["deploy"]
    assert "publish" in job.get("needs", [])
    cond = job.get("if", "")
    assert "inputs.deploy_branch" in cond, "deploy must require a deploy branch"
    assert "inputs.publish == 'true'" in cond, (
        "deploy must not run when publish is false"
    )


def test_reusable_workflow_has_concurrency():
    conc = _load(REUSABLE).get("concurrency")
    assert isinstance(conc, dict), "reusable.yml needs a workflow-level concurrency group"
    assert "github.repository" in conc.get("group", "")
    assert conc.get("cancel-in-progress") is False, (
        "cancel-in-progress must stay false so in-flight publishes are not killed"
    )


def test_validate_publish_artifact_handoff():
    wf = _load(REUSABLE)
    validate_blob = yaml.dump(wf["jobs"]["validate"])
    publish_blob = yaml.dump(wf["jobs"]["publish"])
    assert "docs-tree" in validate_blob, "validate must upload the docs tree"
    assert "docs-tree" in publish_blob, "publish must download the docs tree"


def test_docs_workflow_permissions_and_concurrency():
    wf = _load(DOCS)
    # Workflow-level permissions are required so the reusable workflow's
    # contents:write publish job is not capped down by the caller.
    assert wf.get("permissions", {}).get("contents") == "write"
    assert isinstance(wf.get("concurrency"), dict)


def test_docs_workflow_has_daily_reconciliation_schedule():
    wf = _load(DOCS)
    # PyYAML parses the bare `on:` key as boolean True.
    on = wf.get("on", wf.get(True, {}))
    schedules = on.get("schedule", [])
    assert schedules, "docs.yml must run a scheduled reconciliation"
    cron = schedules[0]["cron"]
    assert len(cron.split()) == 5, f"invalid cron expression: {cron!r}"
    # Existing triggers must be preserved alongside the schedule.
    assert on.get("push", {}).get("branches") == ["main"]
    assert "workflow_dispatch" in on
    # The schedule is serialized with the rest of the docs runs.
    assert wf.get("concurrency", {}).get("cancel-in-progress") is False


def test_docs_call_inputs_are_declared():
    reusable_inputs = set(_inputs(_load(REUSABLE)))
    docs = _load(DOCS)["jobs"]["docs"]
    assert docs["uses"].split("@", 1)[0].endswith("reusable.yml")
    unknown = set(docs.get("with", {})) - reusable_inputs
    assert not unknown, f"docs.yml passes unknown inputs: {sorted(unknown)}"


def test_pypi_publish_workflow_permissions():
    wf = _load(PUBLISH)
    if "permissions" in wf:
        return
    assert any("permissions" in job for job in wf["jobs"].values()), (
        "publish.yml needs a permissions block at workflow or job level"
    )
