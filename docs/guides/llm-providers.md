## LLM Providers

The `repoquill` library provides a unified interface for interacting with Large Language Models (LLMs). This module abstracts the differences between various provider APIs, allowing developers to switch between cloud-based services (such as OpenAI and Anthropic) and local inference engines without modifying their core application logic.

This section documents the configuration, initialization, and usage of the `LLMProvider` abstraction layer. It covers supported providers, required environment variables, and practical examples for generating text completions.

### Overview

The core component for LLM interaction is the `LLMProvider` class, located in `repoquill/llm/provider.py`. This class serves as a factory and manager for specific provider implementations. Each provider implements the `BaseLLM` interface, which defines standard methods for text generation, token counting, and error handling.

Key features include:
*   **Provider Agnosticism:** Switch providers by changing a single configuration parameter.
*   **Environment Variable Support:** Credentials are read from environment variables by default, ensuring secrets are not hardcoded.
*   **Local Model Support:** Integration with local inference servers (e.g., Ollama) for offline or privacy-focused workflows.
*   **Consistent Response Format:** All providers return a standardized `LLMResponse` object, ensuring consistent downstream processing.

### Supported Providers

The following providers are currently supported by `repoquill`:

| Provider | Class Name | Default Model | Requires API Key | Local Option |
| :--- | :--- | :--- | :--- | :--- |
| OpenAI | `OpenAIProvider` | `gpt-4o-mini` | Yes (`OPENAI_API_KEY`) | No |
| Anthropic | `AnthropicProvider` | `claude-3-sonnet` | Yes (`ANTHROPIC_API_KEY`) | No |
| Ollama | `OllamaProvider` | `llama3` | No | Yes |

### Configuration

Configuration is primarily handled via environment variables and the `LLMConfig` dataclass.

#### Environment Variables

To use cloud-based providers, you must set the corresponding API key in your environment:

*   **OpenAI:** `OPENAI_API_KEY`
*   **Anthropic:** `ANTHROPIC_API_KEY`

For local providers like Ollama, no API key is required, but you may need to specify the host and port if not using the defaults (`localhost:11434`).

#### `LLMConfig` Dataclass

The `LLMConfig` class allows for fine-grained control over provider behavior.

```python
from repoquill.llm.config import LLMConfig

config = LLMConfig(
    provider="openai",       # "openai", "anthropic", or "ollama"
    model="gpt-4o",          # Specific model identifier
    temperature=0.7,         # Sampling temperature (0.0 - 2.0)
    max_tokens=1024,         # Maximum tokens to generate
    timeout=30                # Request timeout in seconds
)
```

### Initialization

You can initialize an LLM provider instance using the `get_provider` factory function or by instantiating the specific provider class directly.

#### Using the Factory Function (Recommended)

The `get_provider` function simplifies initialization by handling environment variable lookup and instance creation.

```python
from repoquill.llm.provider import get_provider

# Automatically detects provider from config or defaults to OpenAI
llm = get_provider(provider="openai", model="gpt-4o-mini")

# Or for local models
local_llm = get_provider(provider="ollama", model="llama3", host="localhost", port=11434)
```

#### Direct Instantiation

For advanced use cases where you need to pass custom client instances or interceptors:

```python
from repoquill.llm.providers.openai import OpenAIProvider

# Requires OPENAI_API_KEY to be set in environment
provider = OpenAIProvider(model="gpt-4o", temperature=0.5)
```

### Usage Examples

#### Basic Text Generation

The primary method for interacting with the LLM is `generate`. It accepts a prompt string and optional parameters.

```python
from repoquill.llm.provider import get_provider

# Initialize provider
llm = get_provider(provider="openai", model="gpt-4o-mini")

# Generate text
prompt = "Explain the concept of recursion in Python in one sentence."
response = llm.generate(prompt)

print(response.content)
# Output: Recursion is a programming technique where a function calls itself to solve a problem by breaking it down into smaller, similar sub-problems.
```

#### Multi-Turn Conversations

The `generate` method also supports a `messages` parameter for multi-turn conversations, following the standard chat format.

```python
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "assistant", "content": "The capital of France is Paris."},
    {"role": "user", "content": "And its population?"}
]

response = llm.generate(messages=messages)
print(response.content)
# Output: The population of Paris is approximately 2.1 million people.
```

#### Using Local Models (Ollama)

To use local models, ensure Ollama is installed and running.

```python
# Start Ollama server in terminal: ollama serve

from repoquill.llm.provider import get_provider

# Initialize local provider
local_llm = get_provider(provider="ollama", model="llama3")

# Generate text
response = local_llm.generate("Write a haiku about code.")
print(response.content)
```

### Response Object

All provider methods return an `LLMResponse` object. This object contains the following attributes:

| Attribute | Type | Description |
| :--- | :--- | :--- |
| `content` | `str` | The generated text string. |
| `model` | `str` | The specific model used for generation. |
| `usage` | `dict` | Token usage statistics (e.g., `prompt_tokens`, `completion_tokens`). |
| `provider` | `str` | The name of the provider (e.g., "openai"). |

Example of accessing usage statistics:

```python
response = llm.generate("Hello")
print(f"Tokens used: {response.usage['total_tokens']}")
```

### Error Handling

`repoquill` raises specific exceptions for common failure modes:

*   `LLMProviderError`: General errors related to provider configuration or connection issues.
*   `APIKeyMissingError`: Raised if a required API key is not found in the environment variables.
*   `RateLimitError`: Raised if the provider's rate limit is exceeded.

It is recommended to wrap LLM calls in try-except blocks to handle these gracefully:

```python
from repoquill.llm.errors import LLMProviderError, APIKeyMissingError

try:
    response = llm.generate("Hello")
except APIKeyMissingError:
    print("Error: Please set your API key in the environment.")
except LLMProviderError as e:
    print(f"Provider error: {e}")
```

### Best Practices

1.  **Use Environment Variables:** Never hardcode API keys in your source code. Use `.env` files or system environment variables.
2.  **Set Timeouts:** Always specify a `timeout` in `LLMConfig` to prevent hanging requests.
3.  **Monitor Token Usage:** Check `response.usage` to track costs and ensure you are not exceeding model context limits.
4.  **Cache Responses:** For deterministic prompts, consider caching responses to reduce API costs and latency. `repoquill` does not provide built-in caching, but you can implement it using libraries like `diskcache` or `redis`.

### Troubleshooting

*   **Connection Refused (Ollama):** Ensure the Ollama server is running (`ollama serve`) and the port is not blocked by a firewall.
*   **401 Unauthorized:** Verify that your API key is correct and has not expired. Check for typos in environment variable names.
*   **Timeout Errors:** Increase the `timeout` value in `LLMConfig` or check your network connection. Complex prompts may take longer to process.

By following these guidelines, you can effectively integrate various LLM providers into your `repoquill` applications, leveraging the flexibility and power of modern language models.

### See Also

*   [Architecture](architecture.md)
*   [CI/CD Integration](ci-cd.md)
*   [CLI Commands](cli-commands.md)
*   [Configuration Reference](configuration.md)
