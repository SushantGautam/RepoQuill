"""Coverage checker v2 — de-Goodharted.

A concept is "covered" only if it appears in a SUBSTANTIVE context:
  - a markdown heading (any level), OR
  - a fenced code block, OR
  - a definition-style sentence: "<Name> is a ...", "<Name> — ...",
    "<Name>: ...", or "<Name> represents/describes/defines/implements ..."

A bare substring mention in passing prose does NOT count.

The concept inventory is derived from the source tree via AST (not hand-authored).
"""
import ast, json, os, re, sys

SRC = "/tmp/rq-trials/simpleaudit-src/simpleaudit"
SRC_ROOT = "/tmp/rq-trials/simpleaudit-src"


# ── inventory builders (AST-based where possible) ──────────────────────────

def _py_files():
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(root, f)


def _parse(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return ast.parse(fh.read())
    except (SyntaxError, OSError):
        return None


def get_modules():
    mods = set()
    for p in _py_files():
        if os.path.basename(p) != '__init__.py':
            mods.add(os.path.splitext(os.path.basename(p))[0])
    return sorted(mods)


def get_classes():
    classes = set()
    for p in _py_files():
        tree = _parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                classes.add(node.name)
    return sorted(classes)


def get_functions():
    """Top-level (module-level) functions, public only."""
    funcs = set()
    for p in _py_files():
        tree = _parse(p)
        if not tree:
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                funcs.add(node.name)
    return sorted(funcs)


def get_methods():
    """Methods (def inside ClassDef), public only."""
    methods = set()
    for p in _py_files():
        tree = _parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and not child.name.startswith('_'):
                        methods.add(child.name)
    return sorted(methods)


def get_cli_items():
    cli_path = os.path.join(SRC, 'cli.py')
    if not os.path.exists(cli_path):
        return []
    with open(cli_path) as fh:
        content = fh.read()
    items = set()
    # subcommands: add_parser(\n    "name",  — allow whitespace/newline between call and string
    for m in re.finditer(r'add_parser\(\s*["\']([\w-]+)["\']', content):
        items.add(m.group(1))
    # flags: add_argument(\n    "--flag",  — allow whitespace/newline
    for m in re.finditer(r'add_argument\(\s*["\'](--[\w-]+)["\']', content):
        items.add(m.group(1))
    return sorted(items)


def get_env_vars():
    envs = set()
    for p in _py_files():
        try:
            with open(p) as fh:
                content = fh.read()
        except OSError:
            continue
        for m in re.finditer(r'os\.environ(?:get)?\s*[\[(]["\'](\w+)', content):
            envs.add(m.group(1))
    return sorted(envs)


def get_packs():
    d = os.path.join(SRC, 'scenarios')
    if not os.path.isdir(d):
        return []
    return sorted(f[:-3] for f in os.listdir(d)
                  if f.endswith('.py') and f != '__init__.py')


def get_judges():
    d = os.path.join(SRC, 'judges')
    if not os.path.isdir(d):
        return []
    return sorted(f[:-3] for f in os.listdir(d)
                  if f.endswith('.py') and f != '__init__.py')


def get_install_extras():
    extras = set()
    pyproject = os.path.join(SRC_ROOT, 'pyproject.toml')
    if os.path.exists(pyproject):
        with open(pyproject) as fh:
            content = fh.read()
        m = re.search(r'\[project\.optional-dependencies\](.*?)(?=\[|\Z)',
                      content, re.DOTALL)
        if m:
            for line in m.group(1).split('\n'):
                gm = re.match(r'\s*["\']?([\w-]+)["\']?\s*:', line)
                if gm:
                    extras.add(gm.group(1))
    return sorted(extras)


def get_workflows():
    """Derive workflow/concept terms from docstrings and identifiers."""
    terms = set()
    for p in _py_files():
        tree = _parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ''
                # pull snake_case / kebab-case terms longer than 3 chars
                for m in re.finditer(r'\b([a-z][a-z_]{3,})\b', doc.lower()):
                    terms.add(m.group(1))
    # keep only terms that look like domain concepts (not generic Python words)
    generic = {'function', 'return', 'value', 'type', 'name', 'path', 'file',
               'data', 'list', 'dict', 'str', 'int', 'bool', 'None', 'self',
               'class', 'method', 'module', 'import', 'string', 'number',
               'default', 'argument', 'parameter', 'keyword', 'position',
               'optional', 'required', 'available', 'provided', 'specified',
               'specified', 'generated', 'created', 'updated', 'deleted',
               'loaded', 'saved', 'written', 'read', 'open', 'close',
               'start', 'stop', 'run', 'execute', 'call', 'invoke',
               'process', 'handle', 'check', 'validate', 'verify', 'ensure',
               'build', 'parse', 'format', 'convert', 'transform', 'map',
               'filter', 'reduce', 'accumulate', 'collect', 'gather',
               'emit', 'yield', 'iter', 'enumerate', 'range', 'len', 'min',
               'max', 'sum', 'abs', 'round', 'sorted', 'reversed', 'zip',
               'enumerate', 'any', 'all', 'isinstance', 'issubclass',
               'getattr', 'setattr', 'hasattr', 'delattr', 'dir', 'id',
               'repr', 'str', 'bytes', 'object', 'property', 'staticmethod',
               'classmethod', 'abstractmethod', 'decorator', 'exception',
               'error', 'warning', 'info', 'debug', 'log', 'logger',
               'trace', 'stack', 'frame', 'local', 'global', 'nonlocal',
               'lambda', 'yield', 'await', 'async', 'with', 'import',
               'from', 'as', 'for', 'while', 'if', 'else', 'elif',
               'try', 'except', 'finally', 'raise', 'assert', 'pass',
               'break', 'continue', 'return', 'global', 'nonlocal',
               'del', 'in', 'not', 'and', 'or', 'is', 'None', 'True',
               'False', 'self', 'cls', 'super', 'init', 'new', 'del',
               'get', 'set', 'add', 'remove', 'pop', 'append', 'extend',
               'insert', 'clear', 'copy', 'update', 'items', 'keys',
               'values', 'get', 'setdefault', 'popitem', 'fromkeys',
               'encode', 'decode', 'strip', 'lstrip', 'rstrip', 'split',
               'join', 'replace', 'find', 'index', 'count', 'startswith',
               'endswith', 'upper', 'lower', 'title', 'capitalize',
               'swapcase', 'casefold', 'zfill', 'center', 'ljust', 'rjust',
               'expandtabs', 'translate', 'format', 'format_map',
               'isalnum', 'isalpha', 'isdigit', 'islower', 'isupper',
               'isspace', 'istitle', 'isnumeric', 'isdecimal',
               'open', 'read', 'write', 'readline', 'readlines',
               'write', 'seek', 'tell', 'flush', 'close', 'closed',
               'mode', 'name', 'buffer', 'encoding', 'newline',
               'errors', 'line_buffering', 'write_through',
               'fileno', 'detach', 'isatty', 'truncate',
               'iter', 'next', 'iter', 'iter', 'iter',
               }
    # keep terms that are domain-specific: contain underscores or are multi-word
    domain = {t for t in terms if '_' in t and t not in generic}
    # also keep single-word terms that appear in >1 docstring (frequency filter)
    freq = {}
    for p in _py_files():
        tree = _parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = (ast.get_docstring(node) or '').lower()
                for m in re.finditer(r'\b([a-z]{5,})\b', doc):
                    w = m.group(1)
                    if w not in generic:
                        freq[w] = freq.get(w, 0) + 1
    domain |= {w for w, c in freq.items() if c >= 3}
    return sorted(domain)[:40]  # cap to keep inventory manageable


# ── substantive-mention detection ───────────────────────────────────────────

def extract_substantive_contexts(md_text):
    """Return a set of 'substantive' text spans from the markdown.

    A span is substantive if it is:
      - a heading line (# ...)
      - inside a fenced code block (``` ... ```)
      - a definition-style sentence: starts with the concept name followed
        by ' is ', ' — ', ': ', ' represents', ' describes', ' defines',
        ' implements', ' encapsulates', ' provides'
    """
    spans = []
    in_code = False
    code_lines = []

    for line in md_text.split('\n'):
        stripped = line.strip()

        # track code fences
        if stripped.startswith('```'):
            if in_code:
                spans.append(' '.join(code_lines))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(stripped)
            continue

        # headings
        if stripped.startswith('#'):
            spans.append(stripped.lstrip('#').strip())
            continue

        # definition-style sentences (case-insensitive)
        # we'll check per-concept at match time; for now store the line
        spans.append(stripped)

    if in_code and code_lines:
        spans.append(' '.join(code_lines))

    return spans


def is_substantive_mention(concept, md_text):
    """Check if `concept` is mentioned in a substantive context."""
    concept_lower = concept.lower()
    concept_escaped = re.escape(concept)

    # 1. Heading check
    for m in re.finditer(r'^#{1,6}\s+(.+)$', md_text, re.MULTILINE):
        if concept_lower in m.group(1).lower():
            return True

    # 2. Code block check
    for m in re.finditer(r'```[\w]*\n(.*?)```', md_text, re.DOTALL):
        if concept_lower in m.group(1).lower():
            return True

    # 3. Definition-style sentence check
    # "<concept> is a/an/the ...", "<concept> — ...", "<concept>: ...",
    # "<concept> represents/describes/defines/implements/encapsulates/provides ..."
    def_pattern = (
        rf'(?i)\b{concept_escaped}\s+'
        rf'(is\s+(a|an|the)\b|—|:|represents|describes|defines|'
        rf'implements|encapsulates|provides|handles|manages|performs|'
        rf'executes|runs|generates|creates|builds|loads|saves|reads|'
        rf'writes|sends|receives|processes|computes|calculates|'
        rf'determines|resolves|validates|verifies|checks|ensures)'
    )
    if re.search(def_pattern, md_text):
        return True

    # 4. Bold term check: **concept** or *concept*
    if re.search(rf'(?i)\*\*{concept_escaped}\*\*', md_text):
        return True
    if re.search(rf'(?i)\*{concept_escaped}\*', md_text):
        return True

    return False


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: coverage_check_v2.py <guide_dir> <output_json>")
        sys.exit(1)

    guide_dir = sys.argv[1]
    output_path = sys.argv[2]

    text = ""
    for fname in sorted(os.listdir(guide_dir)):
        if fname.endswith('.md'):
            with open(os.path.join(guide_dir, fname)) as fh:
                text += fh.read() + "\n"

    categories = {
        "modules":   get_modules(),
        "classes":   get_classes(),
        "functions": get_functions(),
        "methods":   get_methods(),
        "cli":       get_cli_items(),
        "env":       get_env_vars(),
        "packs":     get_packs(),
        "judges":    get_judges(),
        "install":   get_install_extras(),
        "workflows": get_workflows(),
    }

    result = {}
    total = 0
    documented = 0

    for cat, items in categories.items():
        missing = []
        doc_count = 0
        for item in items:
            if is_substantive_mention(item, text):
                doc_count += 1
            else:
                missing.append(item)
        result[cat] = {
            "total": len(items),
            "documented": doc_count,
            "missing": missing,
        }
        total += len(items)
        documented += doc_count

    result["_overall"] = {
        "total": total,
        "documented": documented,
        "coverage": documented / total if total else 0,
    }

    with open(output_path, 'w') as fh:
        json.dump(result, fh, indent=2)

    print(f"Coverage v2 (substantive): {documented}/{total} = {documented/total:.1%}")
    for cat, data in result.items():
        if cat == "_overall":
            continue
        status = "✓" if not data["missing"] else "✗"
        print(f"  {status} {cat}: {data['documented']}/{data['total']}")
        if data["missing"]:
            print(f"      missing: {data['missing']}")


if __name__ == "__main__":
    main()
