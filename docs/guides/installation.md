## Installation

`repoquill` is a Python library designed to automate the generation and maintenance of technical documentation directly from repository metadata and source code structures. It streamlines the process of keeping developer documentation synchronized with code changes, reducing manual effort and minimizing documentation drift.

This page provides comprehensive instructions for installing `repoquill` using `pip`, building from source, and managing its dependencies. Whether you are integrating `repoquill` into a CI/CD pipeline or using it locally for development, these steps ensure a stable and reproducible environment.

### Prerequisites

Before installing `repoquill`, ensure your environment meets the following requirements:

1.  **Python Version**: `repoquill` requires **Python 3.8** or higher. It is tested against Python 3.8, 3.9, 3.10, and 3.11.
2.  **Operating System**: Compatible with Linux, macOS, and Windows.
3.  **Package Manager**: `pip` version 20.0 or higher is recommended.

To verify your Python version, run:

```bash
python --version
```

If you do not have a suitable Python version installed, we recommend using a virtual environment manager such as `pyenv` (for macOS/Linux) or `conda` (cross-platform) to manage multiple Python versions.

### Installing via pip

The recommended method for most users is to install `repoquill` directly from the Python Package Index (PyPI). This ensures you get the latest stable release with all dependencies automatically resolved.

#### Standard Installation

To install the latest stable version of `repoquill`, run the following command in your terminal:

```bash
pip install repoquill
```

If you are using a virtual environment, ensure it is activated before running the command. For example, using `venv`:

```bash
python -m venv myenv
source myenv/bin/activate  # On Windows: myenv\Scripts\activate
pip install repoquill
```

#### Installing with Extras

`repoquill` offers optional features that require additional dependencies. You can install these using the `extras` syntax.

*   **`dev`**: Includes development tools such as `pytest`, `black`, `mypy`, and `flake8`. Recommended for contributors.
*   **`docs`**: Includes dependencies required for building the documentation site (e.g., `sphinx`, `sphinx-rtd-theme`).

To install with development tools:

```bash
pip install repoquill[dev]
```

To install with documentation tools:

```bash
pip install repoquill[docs]
```

To install all optional extras:

```bash
pip install repoquill[all]
```

#### Verifying the Installation

After installation, verify that `repoquill` is correctly installed by checking its version:

```bash
python -c "import repoquill; print(repoquill.__version__)"
```

You can also check the available CLI commands if `repoquill` provides a command-line interface:

```bash
repoquill --help
```

### Installing from Source

Installing from source is recommended for developers who wish to contribute to `repoquill` or need to use features from the `main` branch that are not yet available in a stable release.

#### Cloning the Repository

First, clone the `repoquill` repository from GitHub:

```bash
git clone https://github.com/your-org/repoquill.git
cd repoquill
```

#### Creating a Virtual Environment

It is best practice to create an isolated virtual environment for development:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

#### Installing in Editable Mode

Use `pip` to install the package in editable (development) mode. This allows you to make changes to the source code and see them reflected immediately without reinstalling:

```bash
pip install -e .
```

To include development dependencies:

```bash
pip install -e ".[dev]"
```

#### Building Documentation

If you are working on the documentation, you will need to install the documentation extras and build the site:

```bash
pip install -e ".[docs]"
cd docs
make html
```

The generated HTML documentation will be available in the `docs/_build/html` directory.

### Managing Dependencies

`repoquill` uses `setuptools` for package management. The primary dependency definitions are located in the `pyproject.toml` file at the root of the repository.

#### Core Dependencies

The core dependencies required for `repoquill` to function are defined in the `[project.dependencies]` section of `pyproject.toml`. These are installed automatically when you run `pip install repoquill`. Typical core dependencies include:

*   `click`: For command-line interface functionality.
*   `jinja2`: For template rendering of documentation files.
*   `pyyaml`: For parsing YAML configuration files.
*   `requests`: For interacting with GitHub/GitLab APIs if remote metadata is fetched.

#### Optional Dependencies

Optional dependencies are defined under `[project.optional-dependencies]`. As mentioned earlier, these are installed using the bracket notation:

| Extra Name | Description | Included Packages |
| :--- | :--- | :--- |
| `dev` | Development and testing tools | `pytest`, `black`, `mypy`, `flake8`, `pre-commit` |
| `docs` | Documentation building tools | `sphinx`, `sphinx-rtd-theme`, `myst-parser` |
| `all` | All optional dependencies | Union of `dev` and `docs` |

#### Pinning Versions

For production environments, it is recommended to pin specific versions of `repoquill` and its dependencies to ensure reproducibility. You can generate a `requirements.txt` file using:

```bash
pip freeze > requirements.txt
```

Or, for a more curated list, use `pip-tools`:

```bash
pip install pip-tools
pip-compile pyproject.toml -o requirements.txt
```

### Troubleshooting

#### Permission Errors

If you encounter permission errors when installing via `pip`, avoid using `sudo`. Instead, use the `--user` flag or, preferably, a virtual environment:

```bash
pip install --user repoquill
```

#### Conflicting Dependencies

If `repoquill` conflicts with other packages in your environment, consider using a dedicated virtual environment. You can also use `pip check` to identify dependency conflicts:

```bash
pip check
```

#### Build Failures from Source

If building from source fails, ensure that you have the necessary build tools installed:

*   **Linux**: `build-essential`, `python3-dev`
*   **macOS**: Xcode Command Line Tools (`xcode-select --install`)
*   **Windows**: Visual Studio Build Tools with "Desktop development with C++" workload

### Uninstalling

To uninstall `repoquill`, use the following command:

```bash
pip uninstall repoquill
```

This will remove the package and its associated files from your environment.

### Next Steps

Now that you have installed `repoquill`, you can proceed to:

1.  **Configuration**: Set up your `repoquill.yaml` configuration file.
2.  **Usage**: Run the `repoquill` CLI to generate documentation.
3.  **Integration**: Integrate `repoquill` into your CI/CD pipeline for automated documentation updates.

Refer to the **Configuration** and **Usage** sections of this documentation for further details.

### See Also

*   [Quickstart](quickstart.md)
*   [CI/CD Integration](ci-cd.md)
*   [Configuration Reference](configuration.md)
*   [Key Ideas](key-ideas.md)
