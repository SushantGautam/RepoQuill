# RepoQuill Research Mission

RepoQuill is a generic documentation-generation system.

The primary research objective is:

> Maximize factual, comprehensive, useful, well-structured documentation
> generated from arbitrary software repositories while minimizing
> hallucination.

The current benchmark repository is SimpleAudit.

SimpleAudit is a TESTBED, not a target for hard-coded behavior.

## Core rule

Never optimize RepoQuill specifically for SimpleAudit.

Every proposed change must answer:

> Would this reasonably improve documentation for an unrelated repository?

If not, reject it.

## Research methodology

All substantial changes must follow:

1. hypothesis
2. controlled experiment
3. generation from clean state
4. factuality evaluation
5. coverage evaluation
6. usability evaluation
7. comparison against best known result
8. keep or revert

Never keep a change merely because it appears reasonable.

## Source of truth

The source repository is authoritative.

Generated documentation is never evidence about itself.

README files may also be incomplete or wrong; source code, tests, package
metadata, configuration, and examples should be cross-checked.

## Hallucination policy

Extract factual claims from generated docs.

Classify claims as:

- SUPPORTED
- PARTIALLY_SUPPORTED
- UNSUPPORTED
- CONTRADICTED
- UNVERIFIABLE

Unsupported and contradicted statements are severe failures.

Prefer omission or explicit uncertainty over invented detail.

## Delegation

Use subagents aggressively when tasks can be independently investigated.

Prefer parallel agents for:

- repository understanding
- context selection
- prompt experiments
- documentation architecture
- hallucination detection
- factual verification
- coverage evaluation
- parameter experiments
- adversarial review

Do not spawn agents merely to repeat the same analysis.

Agents should return evidence, measurements, and recommendations.

## Independence

Generation and judging should not share hidden assumptions.

Judges must independently inspect the source repository.

At least one evaluator should be adversarial and try to falsify generated
claims.

## Baseline

Always establish and preserve the baseline before changing RepoQuill.

Do not overwrite baseline output.

## Best-known state

Maintain BEST_KNOWN.md with:

- configuration
- prompts
- parameters
- score
- factuality metrics
- coverage metrics
- build status
- known weaknesses

Never replace the best-known result unless the candidate is demonstrably
better overall.

## Documentation generation evaluation

Measure:

- factual correctness
- unsupported claims
- contradicted claims
- feature coverage
- API coverage
- installation correctness
- usage correctness
- example validity
- architecture accuracy
- cross-page consistency
- readability
- navigation
- redundancy
- information density
- usefulness to a new developer

## Local-only experimentation

During research:

- generate locally
- build locally
- serve locally
- inspect locally

Do not depend on GitHub Actions for the experiment loop.

## Continuous research

Finishing one task is not finishing the research goal.

After an experiment completes, choose the next highest-impact uncertainty or
failure mode.

Stop only when multiple consecutive well-motivated experiments fail to yield
meaningful improvement.

## Persistent state

Before ending any session, update:

- CURRENT_STATE.md
- BEST_KNOWN.md
- NEXT_EXPERIMENT.md
- experiments/registry.jsonl

A future Claude session must be able to resume the work without access to the
previous conversation.