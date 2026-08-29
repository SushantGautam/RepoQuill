## Quickstart

Welcome to **repoquill**. This guide provides a minimal, step-by-step example to help you get the library running in under five minutes. `repoquill` is designed to streamline the process of generating and managing technical documentation directly from your Python codebase. It parses source files, extracts docstrings and metadata, and formats them into clean, structured Markdown or HTML output.

### Prerequisites

Before you begin, ensure your environment meets the following requirements:

*   **Python Version:** 3.8 or higher.
*   **Operating System:** Linux, macOS, or Windows.
*   **Dependencies:** The `repoquill` package and its core dependencies.

### Installation

You can install `repoquill` using `pip`. Open your terminal and run the following command:

```bash
pip install repoquill
```

If you are working within a specific virtual environment, ensure it is activated before running the installation command.

### Basic Usage

The core functionality of `repoquill` revolves around the `QuillGenerator` class. This class handles the scanning of directories, parsing of Python modules, and the generation of documentation files.

Below is a minimal example demonstrating how to generate documentation for a single Python file.

#### Step 1: Create a Sample Module

First, create a simple Python file named `example_module.py` in your working directory. This file will serve as the source for our documentation.

```python
# example_module.py

def calculate_area(radius: float) -> float:
    """
    Calculate the area of a circle.

    Args:
        radius (float): The radius of the circle. Must be a positive number.

    Returns:
        float: The calculated area of the circle.

    Raises:
        ValueError: If the radius is negative.
    """
    if radius < 0:
        raise ValueError("Radius cannot be negative")
    return 3.14159 * (radius ** 2)

class DataProcessor:
    """
    A class to process data streams.

    Attributes:
        buffer (list): A list to hold processed data items.
    """

    def __init__(self):
        self.buffer = []

    def add_item(self, item: str):
        """
        Add a single item to the buffer.

        Args:
            item (str): The string item to add.
        """
        self.buffer.append(item)

    def get_summary(self) -> str:
        """
        Return a summary of the buffered items.

        Returns:
            str: A comma-separated string of all items in the buffer.
        """
        return ", ".join(self.buffer)
```

#### Step 2: Initialize the Generator

Import the `QuillGenerator` class and instantiate it. The constructor accepts a `target_path` parameter, which specifies the directory containing the source code, and an `output_dir` parameter, which specifies where the generated documentation should be saved.

```python
from repoquill import QuillGenerator

# Initialize the generator
# 'target_path' is the directory containing your Python files
# 'output_dir' is where the generated Markdown files will be saved
generator = QuillGenerator(
    target_path="./", 
    output_dir="./docs"
)
```

#### Step 3: Generate Documentation

Use the `generate` method to process the files. This method scans the target directory, identifies Python modules, and writes the corresponding documentation files to the output directory.

```python
# Generate documentation for all Python files in the target path
generator.generate()
```

After running this code, you will find a new directory named `docs` in your current working directory. Inside, you will see a file named `example_module.md` containing the generated documentation.

### Configuration Options

The `QuillGenerator` class supports several configuration options to customize the output. These options can be passed during initialization or modified via properties.

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `target_path` | `str` | `"."` | The root directory to scan for Python files. |
| `output_dir` | `str` | `"./docs"` | The directory where generated documentation files are saved. |
| `include_private` | `bool` | `False` | If `True`, includes private methods and classes (prefixed with `_`) in the documentation. |
| `template` | `str` | `"default"` | The name of the template to use for formatting. Currently, only `"default"` is supported. |

#### Example: Custom Configuration

You can customize the generator to include private methods and specify a different output location:

```python
from repoquill import QuillGenerator

generator = QuillGenerator(
    target_path="./src",
    output_dir="./generated_docs",
    include_private=True
)

generator.generate()
```

### Advanced Usage: Specific Files

If you only want to document specific files rather than the entire directory, you can use the `generate_file` method. This method accepts a single file path as an argument.

```python
from repoquill import QuillGenerator

generator = QuillGenerator(output_dir="./docs")

# Generate documentation for a specific file only
generator.generate_file("example_module.py")
```

This approach is useful when you are working on a large codebase and only need to update documentation for modules that have recently changed.

### Output Format

The generated documentation follows a standard Markdown format. Each Python module generates a corresponding `.md` file. The structure typically includes:

1.  **Module Docstring:** If the module has a top-level docstring, it is placed at the beginning of the file.
2.  **Classes:** Each public class is documented with its docstring, attributes, and methods.
3.  **Functions:** Each public function is documented with its docstring, parameters, and return values.
4.  **Code Examples:** If docstrings contain code blocks (using triple backticks), they are preserved in the output.

Here is a snippet of what the generated `example_module.md` might look like:

```markdown
# example_module

## calculate_area(radius: float) -> float

Calculate the area of a circle.

**Args:**
*   `radius` (float): The radius of the circle. Must be a positive number.

**Returns:**
*   float: The calculated area of the circle.

**Raises:**
*   ValueError: If the radius is negative.

## DataProcessor

A class to process data streams.

**Attributes:**
*   `buffer` (list): A list to hold processed data items.

### DataProcessor.add_item(item: str)

Add a single item to the buffer.

**Args:**
*   `item` (str): The string item to add.

### DataProcessor.get_summary() -> str

Return a summary of the buffered items.

**Returns:**
*   str: A comma-separated string of all items in the buffer.
```

### Troubleshooting

*   **File Not Found:** Ensure that the `target_path` or file path provided to `generate_file` is correct and accessible.
*   **Permission Errors:** Ensure that your user has write permissions to the `output_dir`.
*   **Syntax Errors in Source:** `repoquill` relies on Python's AST (Abstract Syntax Tree) for parsing. If your source code contains syntax errors, the generator may fail to parse those files. Ensure your code is valid Python before running the generator.

### Next Steps

Now that you have successfully generated documentation for a simple module, you can explore the following topics:

*   [API Reference](./api-reference.md): Detailed documentation for all classes and methods.
*   [Configuration Guide](./configuration.md): Advanced configuration options and templates.
*   [Integration with CI/CD](./ci-cd.md): How to automate documentation generation in your build pipeline.

By following this quickstart guide, you should now be able to integrate `repoquill` into your development workflow and maintain up-to-date documentation for your Python projects.

### See Also

*   [Installation](installation.md)
*   [Key Ideas](key-ideas.md)
