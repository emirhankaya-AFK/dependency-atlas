# ◈ DependencyAtlas — Python Architecture Explorer

[![Tests](https://github.com/emirhankaya-AFK/dependency-atlas/actions/workflows/ci.yml/badge.svg)](https://github.com/emirhankaya-AFK/dependency-atlas/actions/workflows/ci.yml)

**See every dependency. Break every cycle.** DependencyAtlas scans Python AST trees **without executing project code**. It maps internal imports, finds circular dependency groups, estimates complexity and module coupling, and exports reproducible JSON reports with a local dashboard.

Built with **Python 3.11+, AST, NetworkX, FastAPI**. No paid APIs, cloud account, tracking, external JS libraries, or hosted database.

## Features

- Static `import` and `from ... import ...` analysis, including relative imports and `src/` layouts
- Module dependency graph, strongly connected components (circular dependency groups), fan-in and fan-out metrics
- Simple AST complexity indicator, explainable per-module risk and project health heuristics
- Self-contained interactive browser dashboard with an SVG graph; offline demo
- JSON export from CLI and browser; CI-friendly nonzero exit when cycles or parse errors exist
- ZIP upload restricted to local Python sources with file count, size, path, symlink and decompression limits
- Syntax/encoding errors appear in diagnostic report rather than executing or ignoring them
- Samples, automated tests and GitHub Actions on Python 3.11 / 3.12

## Install and run (local computer)

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Analyze a directory and print JSON:

```bash
dependency-atlas analyze examples/mini_project
dependency-atlas analyze examples/mini_project -o atlas-report.json
# A report file must not already exist; original source files are never modified.
dependency-atlas check examples/mini_project    # exit 2 for a cycle or parse errors
```

Start the local web dashboard:

```bash
dependency-atlas serve
# Visit http://127.0.0.1:8000
# API docs: http://127.0.0.1:8000/docs
```

Upload a project ZIP using the dashboard or API:

```bash
curl -F "file=@my-python-project.zip" http://127.0.0.1:8000/api/analyze > report.json
curl http://127.0.0.1:8000/api/demo
curl http://127.0.0.1:8000/health
```

Run automated tests: `python -m pytest -q`.

## Report shape

- `summary`: modules, internal edges, cyclic groups, modules in cycles, syntax errors, external package count and heuristic health score
- `modules`: source path, lines, functions/classes, AST complexity indicator, fan-in/out, cycle marker and heuristic risk score
- `edges`: `source -> target` internal Python import dependency
- `cycles`: strongly connected components including one-node self-import cycles
- `externals`: imported top-level names outside analyzed files (includes standard library modules)
- `errors`: syntax, encoding and invalid relative imports

**How scores work:** per-module risk is `min(100, 4 × fan_in + 3 × fan_out + 20 if cyclic + min(25, max(0, complexity - 10) × 2))`. Health is `max(0, 100 - min(65, 12 × cyclic_groups + 5 × cyclic_modules) - min(25, 5 × parse_errors))`. These are **heuristics**, not ML predictions or code quality guarantees. AST complexity starts at 1 and adds control-flow/boolean decision nodes; it is **not** McCabe's exact cyclomatic complexity.

## Safety, privacy and known limitations

- **Only local/trusted use.** Web app has no login, authentication, TLS or rate limiting. By default, `serve` binds only `127.0.0.1`; do not expose it on the public internet.
- Uploaded ZIP archives are read into memory and **not persisted by the application**. FastAPI's multipart handling may spool large files temporarily in OS-managed storage. CLI reads files but never executes or modifies them.
- Upload limit: 8 MiB compressed ZIP; 25 MiB claimed uncompressed content, 500 inspected Python files, 512 KiB per `.py` file, 2,000 ZIP entries. Paths and symlinks are checked; no ZIP extraction occurs.
- Static imports only. Dynamic imports (`importlib`, `__import__`), conditional resolution, runtime plugins, import side effects and non-Python dependency files are not evaluated.
- Imports are mapped to modules existing within the scanned source set, not to arbitrary installed packages. Imports of attributes may be attributed to their containing module; star imports are approximated.
- `src/` layouts are supported by a simple heuristic. Namespace packages, multiple source roots and name collisions may require manual review. The top-level project `__init__.py` cannot be represented as a distinct named module.
- Imports appearing inside functions and conditional statements are included as **possible static dependencies** even if branches never execute.
- Errors in individual Python files are reported; other valid modules still contribute to the graph. Some rare encoding/grammar edge cases are reported as parse errors.
- Generated JSON may include internal project structure, module names and paths. Review before sharing it. The dashboard uses `textContent` when displaying untrusted paths and module names.

## License

MIT — see [LICENSE](LICENSE).
