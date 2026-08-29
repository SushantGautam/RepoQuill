## Configuration Reference

The `repoquill` library utilizes a YAML-based configuration file, typically named `repoquill.yml`, to define project metadata, output preferences, and generation rules. This configuration file serves as the primary interface between the user and the documentation generation engine, allowing for fine-grained control over how source code is analyzed and transformed into readable documentation.

This page provides a detailed reference for all supported keys, their data types, default values, and behavioral implications.

### File Location and Syntax

By default, `repoquill` looks for the configuration file in the root directory of the project. You can specify a custom path using the `--config` command-line argument.

The file must be valid YAML. Comments are supported using the `#` symbol.

```yaml
# Example repoquill.yml
project_name: "My Awesome Library"
version: "1.0.0"
output_dir: "./docs"
language: "python"
```

### Global Options

#### `project_name`
- **Type:** `string`
- **Required:** Yes
- **Description:** The human-readable name of the project. This string is used in the header of the generated documentation and in the metadata of the output files.
- **Example:**
  ```yaml
  project_name: "RepoQuill Core"
  ```

#### `version`
- **Type:** `string`
- **Required:** No
- **Default:** `"0.0.1"`
- **Description:** The semantic version of the project. This is included in the documentation footer and can be used for version-controlled documentation builds.
- **Example:**
  ```yaml
  version: "2.4.1"
  ```

#### `output_dir`
- **Type:** `string`
- **Required:** No
- **Default:** `"./docs"`
- **Description:** The relative or absolute path where the generated documentation files will be written. If the directory does not exist, `repoquill` will create it.
- **Example:**
  ```yaml
  output_dir: "/var/www/docs"
  ```

#### `language`
- **Type:** `string`
- **Required:** No
- **Default:** `"python"`
- **Description:** Specifies the primary programming language of the codebase. This affects syntax highlighting in code blocks and the parsing strategy used for docstring extraction.
- **Supported Values:**
  - `"python"`
  - `"javascript"`
  - `"typescript"`
  - `"go"`
- **Example:**
  ```yaml
  language: "python"
  ```

### Source Code Analysis Options

#### `source_dirs`
- **Type:** `list[string]`
- **Required:** No
- **Default:** `["."]`
- **Description:** A list of directories to scan for source code files. Paths are relative to the project root. This allows you to exclude specific modules or include multiple packages.
- **Example:**
  ```yaml
  source_dirs:
    - "src/core"
    - "src/utils"
    - "tests"
  ```

#### `exclude_patterns`
- **Type:** `list[string]`
- **Required:** No
- **Default:** `["*.pyc", "__pycache__", "node_modules"]`
- **Description:** A list of glob patterns to exclude from the source scan. This is useful for ignoring test files, generated code, or third-party libraries.
- **Example:**
  ```yaml
  exclude_patterns:
    - "test_*.py"
    - "*.min.js"
    - "vendor/*"
  ```

#### `include_private`
- **Type:** `boolean`
- **Required:** No
- **Default:** `false`
- **Description:** If set to `true`, `repoquill` will include private methods and classes (those prefixed with an underscore `_`) in the generated documentation. By default, only public APIs are documented.
- **Example:**
  ```yaml
  include_private: true
  ```

### Output Formatting Options

#### `template`
- **Type:** `string`
- **Required:** No
- **Default:** `"default"`
- **Description:** Specifies the HTML template to use for rendering the documentation. `repoquill` ships with several built-in templates.
- **Built-in Templates:**
  - `"default"`: A clean, minimal template.
  - `"sphinx-like"`: Mimics the styling of Sphinx-generated docs.
  - `"github"`: Optimized for embedding in GitHub READMEs.
- **Example:**
  ```yaml
  template: "sphinx-like"
  ```

#### `theme`
- **Type:** `string`
- **Required:** No
- **Default:** `"light"`
- **Description:** The color theme for the generated HTML.
- **Supported Values:**
  - `"light"`
  - `"dark"`
  - `"auto"` (uses system preference)
- **Example:**
  ```yaml
  theme: "dark"
  ```

#### `code_block_style`
- **Type:** `string`
- **Required:** No
- **Default:** `"fenced"`
- **Description:** Determines how code snippets are rendered in the output.
- **Supported Values:**
  - `"fenced"`: Uses triple backticks (```) for Markdown.
  - `"indented"`: Uses 4-space indentation for Markdown.
- **Example:**
  ```yaml
  code_block_style: "fenced"
  ```

### Advanced Configuration

#### `custom_css`
- **Type:** `string`
- **Required:** No
- **Description:** Path to a custom CSS file that will be linked in the generated HTML head. This allows for full branding control.
- **Example:**
  ```yaml
  custom_css: "./assets/styles.css"
  ```

#### `metadata`
- **Type:** `object`
- **Required:** No
- **Description:** A dictionary of key-value pairs that are injected into the HTML `<meta>` tags. Useful for SEO and social media previews.
- **Example:**
  ```yaml
  metadata:
    author: "Jane Doe"
    description: "A powerful documentation generator"
    keywords: "docs, python, automation"
  ```

### Validation and Errors

`repoquill` validates the configuration file before processing begins. Common errors include:

1. **Invalid YAML Syntax:** The parser will throw a `YAMLError` with line and column information.
2. **Missing Required Fields:** If `project_name` is missing, a `ConfigurationError` is raised.
3. **Unsupported Language:** If `language` is set to an unsupported value, a `ValueError` is raised.
4. **Invalid Path:** If `output_dir` points to a location where the user does not have write permissions, an `IOError` is raised.

### Complete Example

Below is a comprehensive `repoquill.yml` file demonstrating most options:

```yaml
# Project Metadata
project_name: "RepoQuill"
version: "1.2.0"
language: "python"

# Source Configuration
source_dirs:
  - "src"
  - "examples"
exclude_patterns:
  - "test_*.py"
  - "conftest.py"
include_private: false

# Output Configuration
output_dir: "./generated_docs"
template: "default"
theme: "light"
code_block_style: "fenced"

# Customization
custom_css: "./static/custom.css"
metadata:
  author: "RepoQuill Team"
  description: "Automated documentation for Python projects"
  keywords: "python, docs, automation, repoquill"
```

### Best Practices

- **Version Control:** Commit your `repoquill.yml` file to version control to ensure consistent documentation builds across environments.
- **Modularization:** For large projects, consider using `source_dirs` to separate core libraries from utility modules, allowing for targeted documentation updates.
- **Testing:** Run `repoquill --validate` to check your configuration file for syntax errors before a full build.

For more information on extending `repoquill` with custom templates, refer to the [Template Development Guide](./templates.md).

### See Also

*   [CLI Commands](cli-commands.md)
*   [CI/CD Integration](ci-cd.md)
*   [Installation](installation.md)
*   [Key Ideas](key-ideas.md)
