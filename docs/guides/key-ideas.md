## Key Ideas

**repoquill** is a Python library designed to streamline the process of generating, managing, and versioning technical documentation directly from source code repositories. Its core philosophy centers on treating documentation as a first-class citizen in the software development lifecycle, ensuring that documentation remains synchronized with the code it describes.

The library is built upon three fundamental abstractions: **Source Abstraction**, **Transformation Pipelines**, and **Artifact Management**. These concepts work together to decouple the source of truth (the code) from the final output format (Markdown, HTML, PDF, etc.), allowing developers to maintain a single source of documentation logic while targeting multiple distribution channels.

### 1. Source Abstraction

At the heart of `repoquill` is the `Source` interface. This abstraction allows the library to ingest documentation content from various origins without coupling the core engine to specific file systems or version control systems.

The primary implementation is `FileSource`, which reads documentation templates and metadata from local files or directories. However, the architecture supports custom sources, enabling integration with remote APIs or database-backed documentation stores.

```python
from repoquill.source import FileSource, Source

class FileSource(Source):
    """
    A source that loads documentation content from the local file system.
    
    Parameters:
        root_path (str): The root directory containing documentation files.
        pattern (str): A glob pattern to match documentation files (default: '*.md').
    """
    def __init__(self, root_path: str, pattern: str = "*.md"):
        self.root_path = root_path
        self.pattern = pattern

    def load(self) -> dict:
        """
        Loads all matching files and returns a dictionary mapping file paths to content.
        """
        # Implementation details...
        pass
```

**Design Pattern:** The *Strategy Pattern* is employed here. By defining a common `Source` interface, `repoquill` can swap out the data retrieval mechanism at runtime without altering the downstream processing logic.

### 2. Transformation Pipelines

Documentation rarely exists in its final form within the source files. It often requires processing steps such as variable substitution, code block execution, or formatting adjustments. `repoquill` models this process as a **Pipeline** of **Transformers**.

A `Transformer` is a callable object that takes a `Document` object and returns a modified `Document`. The `Pipeline` class manages the execution order of these transformers.

#### The `Document` Model

The `Document` class serves as the data carrier through the pipeline. It encapsulates:
*   `content`: The raw text or structured data of the document.
*   `metadata`: A dictionary containing key-value pairs (e.g., title, author, version).
*   `context`: A shared state object available to all transformers in the pipeline.

```python
from repoquill.core import Document, Transformer, Pipeline

class VariableSubstitutionTransformer(Transformer):
    """
    Replaces {{variable}} placeholders in the document content with values from the context.
    """
    def transform(self, doc: Document) -> Document:
        for key, value in doc.context.items():
            doc.content = doc.content.replace(f"{{{{{key}}}}}", str(value))
        return doc

class CodeBlockExecutor(Transformer):
    """
    Executes Python code blocks marked with ```python and replaces them with their output.
    """
    def transform(self, doc: Document) -> Document:
        # Logic to find, execute, and replace code blocks
        return doc
```

#### Building a Pipeline

The `Pipeline` class allows developers to chain transformers together. The order of execution is critical; for example, variable substitution should typically occur before code execution if the code relies on substituted variables.

```python
from repoquill.pipeline import Pipeline
from repoquill.transformers import MarkdownFormatter, TimestampInjector

def create_default_pipeline():
    pipeline = Pipeline()
    
    # 1. Inject current timestamp into metadata
    pipeline.add(TimestampInjector())
    
    # 2. Substitute variables
    pipeline.add(VariableSubstitutionTransformer())
    
    # 3. Format Markdown for consistent styling
    pipeline.add(MarkdownFormatter())
    
    return pipeline
```

**Design Pattern:** The *Chain of Responsibility* pattern is used here. Each transformer handles a specific aspect of the document processing and passes the result to the next transformer in the chain. This promotes modularity and reusability of individual processing steps.

### 3. Artifact Management

Once a document has passed through the transformation pipeline, it needs to be written to a destination. `repoquill` abstracts this through the `Artifact` and `Writer` interfaces.

An `Artifact` represents the final output of a document, including its target file path and format. The `Writer` is responsible for persisting the artifact to the chosen medium (file system, S3, GitHub Pages, etc.).

```python
from repoquill.writer import FileWriter, Writer

class FileWriter(Writer):
    """
    Writes artifacts to the local file system.
    
    Parameters:
        output_dir (str): The directory where output files will be saved.
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def write(self, artifact: Artifact) -> None:
        """
        Writes the artifact content to the specified file path.
        """
        file_path = os.path.join(self.output_dir, artifact.filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(artifact.content)
```

### Core Workflow

The typical usage of `repoquill` follows a clear, linear workflow:

1.  **Initialize Source**: Create a `Source` instance to locate raw documentation files.
2.  **Define Pipeline**: Construct a `Pipeline` with the necessary `Transformer`s.
3.  **Configure Writer**: Set up a `Writer` to handle output.
4.  **Execute**: Run the `RepoQuill` engine to process all documents.

```python
from repoquill import RepoQuill, FileSource, FileWriter
from repoquill.pipeline import Pipeline
from repoquill.transformers import MarkdownFormatter

# 1. Setup Source
source = FileSource(root_path="./docs", pattern="*.md")

# 2. Setup Pipeline
pipeline = Pipeline()
pipeline.add(MarkdownFormatter())

# 3. Setup Writer
writer = FileWriter(output_dir="./build/docs")

# 4. Initialize and Run Engine
engine = RepoQuill(
    source=source,
    pipeline=pipeline,
    writer=writer
)

engine.run()
```

### Configuration and Context

The `context` parameter in the `RepoQuill` engine allows global variables to be injected into every document's processing context. This is useful for injecting build information, such as the current version number or build timestamp, into all generated documents.

```python
engine = RepoQuill(
    source=source,
    pipeline=pipeline,
    writer=writer,
    context={
        "version": "1.0.0",
        "build_date": "2023-10-27"
    }
)
```

Within a `Transformer`, these context variables can be accessed via `doc.context`, enabling dynamic content generation based on the build environment.

### Error Handling and Logging

`repoquill` employs standard Python exception handling. If a `Transformer` fails during execution, the `Pipeline` will raise a `TransformationError` containing the original exception and the document identifier that caused the failure. This allows developers to identify problematic documents without halting the entire build process if configured to continue on error.

```python
try:
    engine.run()
except TransformationError as e:
    logger.error(f"Failed to process document: {e.document_id}")
    logger.error(f"Reason: {e.original_exception}")
```

### Summary of Key Classes

| Class | Module | Description |
| :--- | :--- | :--- |
| `Source` | `repoquill.source` | Abstract base class for data retrieval. |
| `FileSource` | `repoquill.source` | Implementation for local file system sources. |
| `Document` | `repoquill.core` | Data model representing a single document. |
| `Transformer` | `repoquill.core` | Abstract base class for document processing steps. |
| `Pipeline` | `repoquill.pipeline` | Manages the execution order of transformers. |
| `Writer` | `repoquill.writer` | Abstract base class for output persistence. |
| `FileWriter` | `repoquill.writer` | Implementation for local file system output. |
| `RepoQuill` | `repoquill` | Main engine class that orchestrates the workflow. |

By adhering to these abstractions, `repoquill` provides a flexible, extensible framework for documentation generation that can adapt to diverse project needs while maintaining a consistent and predictable API.

### See Also

*   [Architecture](architecture.md)
*   [CI/CD Integration](ci-cd.md)
*   [Configuration Reference](configuration.md)
*   [Installation](installation.md)
