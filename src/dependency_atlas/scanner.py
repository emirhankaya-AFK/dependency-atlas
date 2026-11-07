"""Static Python import analysis. Never imports or executes the inspected project."""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path, PurePosixPath
import stat
import tokenize
import zipfile

import networkx as nx

MAX_FILES = 500
MAX_SOURCE_BYTES = 512 * 1024
MAX_TOTAL_SOURCE_BYTES = 12 * 1024 * 1024
MAX_ZIP_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
IGNORED_DIRS = frozenset({".git", ".venv", "venv", "env", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "node_modules", "build", "dist", "site-packages", ".ruff_cache"})


class ScanError(ValueError):
    """Input is invalid or exceeds local-first safety limits."""


def valid_path(name: str) -> str:
    """Accept only relative POSIX Python filenames without traversal."""
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ScanError("Invalid file path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("..", ".") for part in name.split("/")) or ":" in name.split("/")[0]:
        raise ScanError("Unsafe file path")
    if path.suffix.lower() != ".py":
        raise ScanError("Only Python .py source files can be analyzed")
    return path.as_posix()


def _ignored(path: str) -> bool:
    return any(part in IGNORED_DIRS or part.startswith(".") for part in PurePosixPath(path).parts[:-1])


def decode_python_source(data: bytes) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        return data.decode(encoding)
    except (UnicodeError, SyntaxError, LookupError) as exc:
        raise ScanError("Unsupported or invalid Python source encoding") from exc


def sources_from_directory(root: str | Path) -> dict[str, str]:
    folder = Path(root).expanduser()
    if not folder.is_dir():
        raise ScanError("Project directory does not exist")
    resolved_root = folder.resolve()
    sources: dict[str, str] = {}
    total = 0
    for file in sorted(folder.rglob("*.py")):
        rel = file.relative_to(folder).as_posix()
        if _ignored(rel) or file.is_symlink() or not file.is_file():
            continue
        if not file.resolve().is_relative_to(resolved_root):
            raise ScanError("Source escapes the project directory")
        if len(sources) >= MAX_FILES:
            raise ScanError(f"Maximum {MAX_FILES} Python files allowed")
        size = file.stat().st_size
        total += size
        if size > MAX_SOURCE_BYTES or total > MAX_TOTAL_SOURCE_BYTES:
            raise ScanError("Python source size limit exceeded")
        try:
            sources[rel] = decode_python_source(file.read_bytes())
        except ScanError:
            # Keep the source in the report as a parse error, not an executable file.
            sources[rel] = "\x00"
    if not sources:
        raise ScanError("No Python files found")
    return sources


def sources_from_zip(content: bytes, archive_name: str = "project.zip") -> dict[str, str]:
    if len(content) > MAX_ZIP_BYTES:
        raise ScanError("ZIP exceeds 8 MiB upload limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ScanError("Invalid ZIP archive") from exc
    sources: dict[str, str] = {}
    total_uncompressed = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > 2000:
            raise ScanError("Too many entries in ZIP")
        for entry in infos:
            filename = entry.filename
            # Every entry, including non-Python files, is checked for path traversal.
            if not filename or filename.startswith("/") or "\\" in filename or "\x00" in filename or ":" in filename.split("/")[0] or any(p == ".." for p in filename.split("/")):
                raise ScanError("Unsafe ZIP entry path")
            if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                raise ScanError("ZIP symlinks are not permitted")
            total_uncompressed += entry.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ScanError("ZIP uncompressed size exceeds 25 MiB limit")
            if entry.is_dir() or not filename.endswith(".py") or _ignored(filename):
                continue
            if len(sources) >= MAX_FILES:
                raise ScanError(f"Maximum {MAX_FILES} Python files allowed")
            path = valid_path(filename)
            if path in sources:
                raise ScanError("Duplicate Python file paths in ZIP")
            if entry.file_size > MAX_SOURCE_BYTES:
                raise ScanError("Python source size limit exceeded")
            try:
                raw = archive.read(entry)
            except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
                raise ScanError("Corrupted ZIP entry") from exc
            try:
                sources[path] = decode_python_source(raw)
            except ScanError:
                sources[path] = "\x00"
    if not sources:
        raise ScanError("ZIP contains no Python source files")
    # Most zipped GitHub repos have one containing folder; stripping that root
    # gives the same graph as scanning the repository directory itself.
    first = {p.split("/")[0] for p in sources}
    if len(first) == 1 and all("/" in p for p in sources):
        prefix = next(iter(first))
        repo_wrapper = (prefix == Path(archive_name).stem or prefix.endswith(("-main", "-master"))
                        or any(f"{prefix}/{meta}" in archive.namelist() for meta in ("pyproject.toml", "README.md", ".gitignore")))
        if repo_wrapper and f"{prefix}/__init__.py" not in sources:
            sources = {p.split("/", 1)[1]: value for p, value in sources.items()}
    return sources


def _module_name(path: str, strip_src: bool) -> tuple[str, bool]:
    parts = PurePosixPath(path).with_suffix("").parts
    if strip_src and parts[0] == "src":
        parts = parts[1:]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _resolve(name: str, modules: set[str]) -> str | None:
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in modules:
            return candidate
    return None


def _relative_base(module: str, package: bool, level: int, target: str | None) -> str | None:
    parents = module.split(".") if package else module.split(".")[:-1]
    if level - 1 > len(parents) or not parents:
        return None
    prefix = parents[:len(parents) - level + 1]
    return ".".join([*prefix, *([target] if target else [])])


def analyze_sources(sources: dict[str, str], project_name: str = "project") -> dict:
    """Build deterministic report from relative paths and Python source strings."""
    if not sources:
        raise ScanError("No Python files found")
    if len(sources) > MAX_FILES:
        raise ScanError("Too many Python files")
    total = 0
    validated = {}
    for path, source in sources.items():
        key = valid_path(path)
        if _ignored(key):
            continue
        if not isinstance(source, str):
            raise ScanError("Source must be text")
        size = len(source.encode("utf-8"))
        total += size
        if size > MAX_SOURCE_BYTES or total > MAX_TOTAL_SOURCE_BYTES:
            raise ScanError("Python source size limit exceeded")
        validated[key] = source
    if not validated:
        raise ScanError("No Python files found")
    strip_src = any(p.startswith("src/") for p in validated) and "src/__init__.py" not in validated
    lookup: dict[str, tuple[str, bool, str]] = {}
    for path, source in sorted(validated.items()):
        name, package = _module_name(path, strip_src)
        if not name:
            continue
        if name not in lookup:
            lookup[name] = (path, package, source)
    if not lookup:
        raise ScanError("No importable Python modules found")
    module_names = set(lookup)
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(module_names))
    rows: dict[str, dict] = {}
    externals: set[str] = set()
    errors: list[dict] = []
    for module, (path, is_package, source) in sorted(lookup.items()):
        lines = len(source.splitlines())
        row = {"module": module, "path": path, "lines": lines, "functions": 0, "classes": 0,
               "complexity": 0, "fan_in": 0, "fan_out": 0, "risk_score": 0, "in_cycle": False}
        rows[module] = row
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as exc:
            errors.append({"file": path, "line": getattr(exc, "lineno", None), "reason": "Python syntax or encoding error"})
            continue
        nodes = list(ast.walk(tree))
        row["functions"] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in nodes)
        row["classes"] = sum(isinstance(n, ast.ClassDef) for n in nodes)
        row["complexity"] = 1 + sum(isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                                  ast.ExceptHandler, ast.IfExp, ast.Assert, ast.Match)) for n in nodes) + sum(max(0, len(n.values) - 1) for n in nodes if isinstance(n, ast.BoolOp))
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _resolve(alias.name, module_names)
                    if target:
                        graph.add_edge(module, target)
                    else:
                        externals.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = _relative_base(module, is_package, node.level, node.module)
                    if base is None:
                        errors.append({"file": path, "line": node.lineno, "reason": "Relative import exceeds package root"})
                        continue
                else:
                    base = node.module or ""
                resolved_any = False
                for alias in node.names:
                    candidate = f"{base}.{alias.name}" if base and alias.name != "*" else base
                    target = _resolve(candidate, module_names) or _resolve(base, module_names)
                    if target:
                        graph.add_edge(module, target)
                        resolved_any = True
                if not resolved_any and node.level == 0 and base:
                    externals.add(base.split(".")[0])
    components = list(nx.strongly_connected_components(graph))
    cycles = sorted([sorted(c) for c in components if len(c) > 1 or (len(c) == 1 and graph.has_edge(next(iter(c)), next(iter(c))))], key=lambda x: (x[0], len(x)))
    cyclic = {module for group in cycles for module in group}
    for module, row in rows.items():
        row["fan_in"] = graph.in_degree(module)
        row["fan_out"] = graph.out_degree(module)
        row["in_cycle"] = module in cyclic
        row["risk_score"] = min(100, 4 * row["fan_in"] + 3 * row["fan_out"] + (20 if module in cyclic else 0) + min(25, max(0, row["complexity"] - 10) * 2))
    edges = [{"source": a, "target": b} for a, b in sorted(graph.edges)]
    health = max(0, 100 - min(65, 12 * len(cycles) + 5 * len(cyclic)) - min(25, 5 * len(errors)))
    return {"project": project_name[:100],
            "summary": {"total_modules": len(rows), "total_edges": len(edges), "cycles_found": len(cycles),
                        "cyclic_modules": len(cyclic), "parse_errors": len(errors), "external_packages": len(externals),
                        "health_score": health},
            "modules": [rows[n] for n in sorted(rows)], "edges": edges,
            "cycles": cycles, "externals": sorted(externals), "errors": errors,
            "notes": ["Static AST analysis only: dynamic imports and runtime dependency injection are not detected.",
                      "Risk and health scores are transparent heuristics, not AI predictions or security guarantees.",
                      "Imports of third-party libraries are reported by top-level package name; they are not resolved to dependency versions."]}


def analyze_directory(path: str | Path) -> dict:
    p = Path(path).expanduser()
    return analyze_sources(sources_from_directory(p), p.name)


def analyze_zip(data: bytes, filename: str = "project.zip") -> dict:
    if not filename.lower().endswith(".zip"):
        raise ScanError("Upload a .zip archive of a Python project")
    name = Path(filename).name.removesuffix(".zip")
    return analyze_sources(sources_from_zip(data, filename), name)


def as_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
