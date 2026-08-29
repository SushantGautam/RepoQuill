## CI/CD Integration

Automating documentation generation is essential for maintaining accurate, up-to-date technical documentation in large-scale software projects. The `repoquill` library provides robust support for Continuous Integration and Continuous Deployment (CI/CD) pipelines, allowing developers to integrate documentation regeneration directly into their build processes. By leveraging GitHub Actions, you can ensure that every code change triggers a verification or regeneration of the documentation, preventing drift between the codebase and its associated docs.

This section details how to configure GitHub Actions workflows to automatically run `repoquill` scripts, handle versioning, and deploy generated documentation to static hosting services.

### Prerequisites

Before setting up CI/CD integration, ensure the following prerequisites are met in your project:

1.  **Python Environment**: The CI runner must have Python 3.8+ installed.
2.  **Dependencies**: Your project must define dependencies in a `pyproject.toml`, `setup.py`, or `requirements.txt` file.
3.  **Repoquill Configuration**: A valid `repoquill.toml` or equivalent configuration file must exist in the repository root to define documentation sources and output targets.
4.  **Secrets**: If deploying to a private repository or using authenticated APIs, configure the necessary GitHub Secrets (e.g., `GITHUB_TOKEN`, `NPM_TOKEN`).

### Basic GitHub Actions Workflow

The following workflow example demonstrates a standard CI pipeline that installs dependencies, runs the `repoquill` generator, and uploads the generated artifacts. This workflow triggers on pushes to the `main` branch and on pull requests.

```yaml
name: Documentation Build

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build-docs:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e .
        # If repoquill is not part of the main package, install it explicitly
        # pip install repoquill

    - name: Generate Documentation
      run: |
        # Execute the repoquill CLI to generate docs
        # The 'generate' command reads from repoquill.toml by default
        python -m repoquill generate --output ./docs/generated

    - name: Validate Documentation
      run: |
        # Optional: Run linting or validation checks on generated markdown
        # python -m repoquill validate ./docs/generated

    - name: Upload Artifacts
      uses: actions/upload-artifact@v4
      with:
        name: generated-docs
        path: ./docs/generated
```

### Configuration Options for CI

The `repoquill` CLI supports several flags that are particularly useful in CI environments where determinism and speed are critical.

| Flag | Description | CI Recommendation |
| :--- | :--- | :--- |
| `--output <path>` | Specifies the directory where generated documentation is written. | Use a dedicated directory (e.g., `./docs/generated`) that is ignored by Git but captured by artifacts. |
| `--strict` | Fails the build if any documentation source cannot be parsed or resolved. | **Recommended**. Ensures broken docstrings or missing references fail the CI pipeline immediately. |
| `--no-cache` | Disables the internal cache mechanism. | Use in CI to ensure fresh generation on every run, avoiding stale data from cached states. |
| `--verbose` | Enables detailed logging output. | Useful for debugging generation failures in CI logs. |

### Advanced: Deploying to GitHub Pages

If your project uses GitHub Pages for hosting documentation, you can extend the workflow to deploy the generated output. Note that `repoquill` generates static files (Markdown, HTML, or JSON depending on your config), which are suitable for static hosting.

```yaml
name: Deploy Documentation

on:
  push:
    branches: [ main ]

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install and Generate
      run: |
        pip install -e .
        python -m repoquill generate --output ./docs/generated --strict

    - name: Deploy to GitHub Pages
      uses: peaceiris/actions-gh-pages@v3
      with:
        github_token: ${{ secrets.GITHUB_TOKEN }}
        publish_dir: ./docs/generated
        # Optional: Configure publish_branch if not using 'gh-pages'
        # publish_branch: gh-pages
```

### Handling Versioning and Tags

For projects that release versions, it is often desirable to tag documentation builds with version numbers. `repoquill` can inject version information into the generated metadata if configured in `repoquill.toml`.

In your `repoquill.toml`, ensure the `metadata` section includes a placeholder for the version:

```toml
[metadata]
title = "Project Documentation"
version = "{{ version }}"  # This will be replaced by the CI environment variable
```

In your GitHub Actions workflow, you can pass the version via an environment variable or by parsing it from the git tag:

```yaml
    - name: Set Version
      run: |
        # Extract version from git tag or use a default
        VERSION=$(git describe --tags --always --dirty)
        echo "VERSION=$VERSION" >> $GITHUB_ENV

    - name: Generate Documentation
      env:
        REPOQUILL_VERSION: ${{ env.VERSION }}
      run: |
        # Some configurations allow environment variable interpolation
        # Check your repoquill.toml for environment variable support
        python -m repoquill generate --output ./docs/generated
```

*Note: Direct environment variable interpolation depends on your specific `repoquill` configuration schema. If not natively supported, you may need to use a pre-processing script to update the configuration file before running the generator.*

### Best Practices

1.  **Fail Fast**: Always use the `--strict` flag in CI. Documentation errors should block merges to prevent technical debt.
2.  **Cache Dependencies**: Use `actions/cache` to cache pip packages to reduce workflow execution time.
    ```yaml
    - name: Cache pip
      uses: actions/cache@v4
      with:
        path: ~/.cache/pip
        key: ${{ runner.os }}-pip-${{ hashFiles('**/pyproject.toml') }}
        restore-keys: |
          ${{ runner.os }}-pip-
    ```
3.  **Separate Build and Deploy**: Keep documentation generation in a separate job from deployment. This allows you to cache the generated docs and only deploy when the content actually changes.
4.  **Log Output**: Ensure `--verbose` is enabled in CI logs for easier debugging of generation issues.
5.  **Artifact Retention**: Configure artifact retention policies to avoid storage bloat. For example, keep only the last 5 builds.

### Troubleshooting

*   **Permission Denied**: Ensure the output directory specified in `--output` is writable by the CI user.
*   **Missing Sources**: If `repoquill` fails to find source files, verify that the `paths` defined in `repoquill.toml` are relative to the repository root and that the files exist in the CI checkout.
*   **Version Mismatch**: Ensure the version of `repoquill` installed in CI matches the version used in local development to avoid schema incompatibilities.

By integrating `repoquill` into your CI/CD pipeline, you ensure that documentation remains a first-class citizen in your development workflow, automatically validated and updated with every code change.

### See Also

*   [CLI Commands](cli-commands.md)
*   [Quickstart](quickstart.md)
*   [Configuration Reference](configuration.md)
*   [Installation](installation.md)
