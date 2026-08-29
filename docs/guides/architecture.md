## Architecture

**repoquill** is a lightweight Python library designed to streamline the generation of developer documentation directly from source code repositories. Its primary objective is to bridge the gap between raw code and readable, maintainable documentation by analyzing repository structures, extracting metadata, and rendering formatted output.

The architecture of `repoquill` is modular, allowing for independent extension of parsing, analysis, and rendering components. This section provides a high-level overview of the system design, module interactions, and data flow.

### System Overview

The `repoquill` system operates on a pipeline model. Data flows from the source repository through a series of processing stages:

1.  **Discovery**: Identifying relevant files and directories within the repository.
2.  **Parsing**: Extracting structural information (classes, functions, docstrings) from source files.
3.  **Analysis**: Processing extracted data to determine relationships, dependencies, and documentation gaps.
4.  **Rendering**: Converting the analyzed data into the target documentation format (e.g., Markdown, HTML).

This separation of concerns ensures that the core logic remains agnostic to the specific programming language being analyzed or the output format being generated.

### Core Modules

The library is organized into several key modules, each responsible for a specific aspect of the documentation generation pipeline.

#### 1. `repoquill.core`

This module contains the primary entry points and high-level orchestration logic.

*   **`RepositoryScanner`**:
    *   **Description**: Responsible for traversing the file system to identify source code files. It respects `.gitignore` patterns and configurable inclusion/exclusion rules.
    *   **Key Methods**:
        *   `scan(root_path: str, extensions: list[str] = None) -> list[Path]`: Scans the directory tree and returns a list of file paths matching the specified extensions.
        *   `filter_files(files: list[Path], ignore_patterns: list[str]) -> list[Path]`: Applies filtering logic to exclude specific files or directories.

*   **`DocGenerator`**:
    *   **Description**: The main orchestrator that coordinates the scanning, parsing, and rendering processes.
    *   **Key Methods**:
        *   `generate(repo_path: str, output_dir: str, format: str = "markdown") -> None`: Executes the full documentation generation pipeline.
        *   `configure(options: dict)`: Allows runtime configuration of the generator (e.g., enabling/disabling specific analyzers).

#### 2. `repoquill.parsers`

This module contains language-specific parsers that extract structural information from source files.

*   **`BaseParser`**:
    *   **Description**: An abstract base class defining the interface for all language parsers.
    *   **Abstract Methods**:
        *   `parse(file_path: Path) -> ASTNode`: Parses a single file and returns an Abstract Syntax Tree (AST) representation.
        *   `supported_extensions() -> list[str]`: Returns the file extensions this parser supports.

*   **`PythonParser`**:
    *   **Description**: A concrete implementation of `BaseParser` for Python files. It utilizes the `ast` module from the Python standard library.
    *   **Features**:
        *   Extracts class definitions, function signatures, and docstrings.
        *   Handles type annotations.
        *   Identifies module-level constants.

*   **`ASTNode`**:
    *   **Description**: A data structure representing a node in the parsed syntax tree.
    *   **Attributes**:
        *   `name`: The name of the entity (e.g., function or class name).
        *   `type`: The type of the node (e.g., `CLASS`, `FUNCTION`, `MODULE`).
        *   `docstring`: The raw docstring content, if present.
        *   `children`: A list of child `ASTNode` objects.
        *   `metadata`: A dictionary for additional metadata (e.g., line numbers, decorators).

#### 3. `repoquill.analyzers`

This module processes the AST nodes to derive higher-level insights.

*   **`DependencyAnalyzer`**:
    *   **Description**: Analyzes imports and references to build a dependency graph.
    *   **Key Methods**:
        *   `analyze(nodes: list[ASTNode]) -> DependencyGraph`: Returns a graph structure representing module and class dependencies.

*   **`CoverageAnalyzer`**:
    *   **Description**: Identifies undocumented entities (functions or classes without docstrings).
    *   **Key Methods**:
        *   `find_gaps(nodes: list[ASTNode]) -> list[ASTNode]`: Returns a list of nodes missing documentation.

#### 4. `repoquill.renderers`

This module handles the conversion of analyzed data into human-readable formats.

*   **`BaseRenderer`**:
    *   **Description**: An abstract base class for output renderers.
    *   **Abstract Methods**:
        *   `render(data: DocumentationData) -> str`: Converts the documentation data model into a string representation.
        *   `file_extension() -> str`: Returns the file extension for the output format.

*   **`MarkdownRenderer`**:
    *   **Description**: Renders documentation in Markdown format.
    *   **Features**:
        *   Generates tables of contents.
        *   Formats code blocks with syntax highlighting hints.
        *   Structures output by module and class.

### Data Flow

The following sequence describes the data flow during a typical documentation generation run:

1.  **Initialization**: The user instantiates `DocGenerator` and calls `generate()`.
2.  **Scanning**: `RepositoryScanner` traverses the repository, returning a list of `Path` objects for all supported source files.
3.  **Parsing**: For each file, the appropriate parser (e.g., `PythonParser`) is selected based on file extension. The parser reads the file and constructs an `ASTNode` tree.
4.  **Aggregation**: All `ASTNode` trees are aggregated into a single `DocumentationData` object, which serves as the central data model for the pipeline.
5.  **Analysis**: Analyzers (e.g., `DependencyAnalyzer`) process the `DocumentationData` to enrich it with additional information such as dependency links and coverage metrics.
6.  **Rendering**: The selected renderer (e.g., `MarkdownRenderer`) consumes the enriched `DocumentationData` and produces the final output string.
7.  **Output**: The rendered string is written to the specified output directory.

### Configuration

`repoquill` supports configuration via a dictionary passed to `DocGenerator.configure()`. Key configuration options include:

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `extensions` | `list[str]` | `[".py"]` | File extensions to include in the scan. |
| `ignore_patterns` | `list[str]` | `["test_", "conftest"]` | Patterns to exclude from documentation. |
| `output_format` | `str` | `"markdown"` | The target documentation format. |
| `include_private` | `bool` | `False` | Whether to include private methods/classes. |

### Example Usage

The following example demonstrates how to use `repoquill` to generate Markdown documentation for a Python project.

```python
from repoquill.core import DocGenerator

def main():
    # Initialize the generator
    generator = DocGenerator()
    
    # Configure the generator
    generator.configure({
        "extensions": [".py"],
        "ignore_patterns": ["test_", "migrations"],
        "output_format": "markdown"
    })
    
    # Generate documentation
    # This will scan the current directory and output to ./docs
    generator.generate(
        repo_path=".",
        output_dir="./docs"
    )
    
    print("Documentation generated successfully.")

if __name__ == "__main__":
    main()
```

### Design Principles

1.  **Extensibility**: New language parsers can be added by subclassing `BaseParser`. New output formats can be added by subclassing `BaseRenderer`.
2.  **Separation of Concerns**: Parsing, analysis, and rendering are decoupled, allowing for independent testing and optimization.
3.  **Performance**: The scanner uses efficient file system traversal, and parsers are designed to handle large codebases without excessive memory consumption.
4.  **Accuracy**: The library relies on standard library parsing tools (e.g., `ast` for Python) to ensure accurate extraction of code structure.

By adhering to these principles, `repoquill` provides a robust and flexible foundation for automated documentation generation in software projects.

### See Also

*   [Key Ideas](key-ideas.md)
