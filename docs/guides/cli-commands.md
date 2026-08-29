## CLI Commands

The `repoquill` library provides a robust Command-Line Interface (CLI) designed for seamless integration into development workflows, CI/CD pipelines, and local development environments. The CLI serves as the primary entry point for interacting with the core documentation generation engine, allowing developers to configure, execute, and manage documentation tasks without writing Python scripts.

This module is implemented within the `repoquill.cli` package, specifically leveraging the `argparse` standard library for argument parsing and the `click` library for enhanced user experience features such as colored output and command grouping. The main entry point is defined in `repoquill/__main__.py`, which delegates execution to the `main()` function in `repoquill/cli/main.py`.

### Overview

The CLI supports three primary modes of operation:
1.  **Generate**: Creates or updates documentation files based on source code analysis.
2.  **Validate**: Checks the consistency and completeness of existing documentation against the codebase.
3.  **Config**: Manages configuration files, including initialization and validation.

All commands support global flags for logging, verbosity, and output formatting. The CLI is designed to be non-interactive by default, making it suitable for automated environments, but includes flags to enable interactive prompts when necessary.

### Global Options

These options are available for all subcommands and can be placed before or after the subcommand name, depending on the specific command implementation.

| Flag | Description | Default |
| :--- | :--- | :--- |
| `-v`, `--verbose` | Enable verbose logging. Can be used multiple times for increasing detail. | `False` |
| `-q`, `--quiet` | Suppress all output except for critical errors. | `False` |
| `--version` | Display the current version of `repoquill` and exit. | N/A |
| `--help` | Show help message and exit. | N/A |
| `--config-file` | Path to the configuration file. If not provided, defaults to `repoquill.yaml` in the current directory. | `./repoquill.yaml` |

### Command: `generate`

The `generate` command is the core functionality of `repoquill`. It scans the specified source directories, analyzes the code, and writes the generated documentation to the target directory.

**Usage:**
```bash
repoquill generate [OPTIONS]
```

**Options:**

| Flag | Description |
| :--- | :--- |
| `--source-dir` | The root directory containing the source code. Defaults to the current working directory. |
| `--output-dir` | The directory where documentation files will be written. Defaults to `./docs`. |
| `--format` | Output format. Supported values: `markdown` (default), `html`, `json`. |
| `--force` | Overwrite existing documentation files without confirmation. |
| `--ignore` | Comma-separated list of glob patterns to ignore during scanning (e.g., `*.test.py,tests/*`). |
| `--workers` | Number of parallel worker processes to use for analysis. Defaults to `1`. |

**Example:**
```bash
# Generate Markdown documentation for the current project
repoquill generate --format markdown --output-dir ./docs

# Generate HTML documentation with parallel processing
repoquill generate --format html --workers 4 --force
```

### Command: `validate`

The `validate` command checks the integrity of the documentation. It verifies that all public modules and functions are documented, that docstrings are present, and that the documentation structure matches the code structure. This command does not modify any files.

**Usage:**
```bash
repoquill validate [OPTIONS]
```

**Options:**

| Flag | Description |
| :--- | :--- |
| `--source-dir` | The root directory containing the source code. |
| `--docs-dir` | The directory containing the existing documentation. Defaults to `./docs`. |
| `--strict` | Treat warnings as errors. If enabled, the command exits with a non-zero status code if any warnings are found. |
| `--report` | Path to save a detailed validation report in JSON format. |

**Exit Codes:**
- `0`: Validation passed successfully.
- `1`: Validation failed (errors found).
- `2`: Configuration or file access error.

**Example:**
```bash
# Validate documentation in strict mode
repoquill validate --strict

# Validate and save a report
repoquill validate --report validation_report.json
```

### Command: `config`

The `config` command manages the `repoquill.yaml` configuration file. It allows users to initialize a new configuration, view the current effective configuration, and validate the configuration syntax.

**Usage:**
```bash
repoquill config [SUBCOMMAND]
```

#### Subcommand: `init`

Creates a new `repoquill.yaml` file with default settings. If the file already exists, it will not be overwritten unless the `--force` flag is used.

**Options:**
- `--force`: Overwrite existing configuration file.
- `--template`: Name of the template to use (e.g., `basic`, `advanced`). Defaults to `basic`.

**Example:**
```bash
# Initialize a new configuration file
repoquill config init

# Initialize with an advanced template
repoquill config init --template advanced
```

#### Subcommand: `show`

Displays the current effective configuration. This merges the default configuration, the file-based configuration, and any environment variables.

**Example:**
```bash
repoquill config show
```

#### Subcommand: `validate`

Checks the syntax and semantics of the configuration file without executing any documentation tasks.

**Example:**
```bash
repoquill config validate
```

### Configuration File Structure

The CLI relies on a YAML configuration file (`repoquill.yaml`) for persistent settings. The following is a reference for the keys supported in the configuration file:

```yaml
# repoquill.yaml
project:
  name: "MyProject"
  version: "1.0.0"

source:
  directories:
    - "src/"
    - "lib/"
  ignore:
    - "*.pyc"
    - "__pycache__/"
    - "tests/"

output:
  directory: "./docs"
  format: "markdown"
  template: "default"

logging:
  level: "INFO"
  file: "./repoquill.log"
```

### Environment Variables

The CLI respects the following environment variables, which can override configuration file settings:

| Variable | Description |
| :--- | :--- |
| `REPOQUILL_CONFIG` | Path to the configuration file. Overrides `--config-file`. |
| `REPOQUILL_LOG_LEVEL` | Sets the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `REPOQUILL_OUTPUT_DIR` | Overrides the output directory specified in the config or CLI. |

### Error Handling

The CLI provides clear error messages for common issues:
- **File Not Found**: If the specified source or output directory does not exist.
- **Invalid Configuration**: If the YAML file contains syntax errors or unsupported keys.
- **Permission Denied**: If the output directory is not writable.

In all error cases, the CLI exits with a non-zero status code and prints a detailed traceback to `stderr` if `--verbose` is enabled.

### Integration with CI/CD

For continuous integration, it is recommended to use the `validate` command to ensure documentation consistency before merging code. The `generate` command can be used to build documentation artifacts for deployment.

**Example GitHub Actions Workflow:**
```yaml
- name: Validate Documentation
  run: repoquill validate --strict

- name: Generate Documentation
  run: repoquill generate --format html --output-dir ./public/docs

- name: Deploy Documentation
  uses: actions/deploy@v1
  with:
    path: ./public/docs
```

### Troubleshooting

If the CLI fails to recognize a command, ensure that `repoquill` is installed in the active Python environment. You can verify the installation by running:

```bash
python -m repoquill --version
```

If you encounter issues with parallel processing (`--workers`), try reducing the number of workers or disabling parallelism entirely by setting `--workers 1`. This can help identify if the issue is related to resource contention or file locking.

### See Also

*   [CI/CD Integration](ci-cd.md)
*   [Configuration Reference](configuration.md)
*   [Quickstart](quickstart.md)
