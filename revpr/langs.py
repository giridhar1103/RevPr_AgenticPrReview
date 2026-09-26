"""Per-language Tree-sitter node tables.

Each entry tells the parser which node types define symbols, which are call sites, which are
imports and which add a branch for complexity. Languages not listed here are still chunked by
lines and indexed lexically.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LangSpec:
    name: str
    exts: tuple[str, ...]
    # node type -> symbol kind
    defs: dict[str, str]
    # node type -> field holding the callee (None: first named child)
    calls: dict[str, str | None]
    imports: tuple[str, ...]
    branches: tuple[str, ...]
    # node types whose children are definitions (class bodies etc.), used for method detection
    containers: tuple[str, ...] = ()
    test_markers: tuple[str, ...] = ()
    extra_names: dict[str, str] = field(default_factory=dict)


_C_BRANCHES = ("if_statement", "for_statement", "while_statement", "do_statement",
               "case_statement", "conditional_expression", "catch_clause")

LANGS: dict[str, LangSpec] = {
    "python": LangSpec(
        "python", (".py", ".pyi"),
        defs={"function_definition": "function", "class_definition": "class"},
        calls={"call": "function", "decorator": None},
        imports=("import_statement", "import_from_statement"),
        branches=("if_statement", "elif_clause", "for_statement", "while_statement",
                  "except_clause", "conditional_expression", "boolean_operator",
                  "list_comprehension", "case_clause"),
        containers=("class_definition",),
    ),
    "javascript": LangSpec(
        "javascript", (".js", ".jsx", ".mjs", ".cjs"),
        defs={"function_declaration": "function", "generator_function_declaration": "function",
              "class_declaration": "class", "method_definition": "method",
              "variable_declarator": "function"},
        calls={"call_expression": "function", "new_expression": "constructor"},
        imports=("import_statement",),
        branches=_C_BRANCHES + ("switch_case", "ternary_expression"),
        containers=("class_declaration",),
    ),
    "typescript": LangSpec(
        "typescript", (".ts", ".mts", ".cts"),
        defs={"function_declaration": "function", "class_declaration": "class",
              "abstract_class_declaration": "class", "method_definition": "method",
              "interface_declaration": "interface", "type_alias_declaration": "type",
              "enum_declaration": "type", "variable_declarator": "function"},
        calls={"call_expression": "function", "new_expression": "constructor"},
        imports=("import_statement",),
        branches=_C_BRANCHES + ("switch_case", "ternary_expression"),
        containers=("class_declaration", "abstract_class_declaration"),
    ),
    "tsx": LangSpec(
        "tsx", (".tsx",),
        defs={"function_declaration": "function", "class_declaration": "class",
              "method_definition": "method", "interface_declaration": "interface",
              "type_alias_declaration": "type", "variable_declarator": "function"},
        calls={"call_expression": "function", "new_expression": "constructor"},
        imports=("import_statement",),
        branches=_C_BRANCHES + ("switch_case", "ternary_expression"),
        containers=("class_declaration",),
    ),
    "go": LangSpec(
        "go", (".go",),
        defs={"function_declaration": "function", "method_declaration": "method",
              "type_spec": "type"},
        calls={"call_expression": "function"},
        imports=("import_spec",),
        branches=("if_statement", "for_statement", "expression_case", "type_case",
                  "communication_case"),
    ),
    "java": LangSpec(
        "java", (".java",),
        defs={"class_declaration": "class", "interface_declaration": "interface",
              "enum_declaration": "type", "record_declaration": "class",
              "method_declaration": "method", "constructor_declaration": "method"},
        calls={"method_invocation": "name", "object_creation_expression": "type"},
        imports=("import_declaration",),
        branches=_C_BRANCHES + ("switch_label", "enhanced_for_statement", "ternary_expression"),
        containers=("class_declaration", "interface_declaration", "enum_declaration"),
    ),
    "kotlin": LangSpec(
        "kotlin", (".kt", ".kts"),
        defs={"class_declaration": "class", "object_declaration": "class",
              "function_declaration": "function"},
        calls={"call_expression": None},
        imports=("import_header",),
        branches=("if_expression", "for_statement", "while_statement", "when_entry",
                  "catch_block"),
    ),
    "rust": LangSpec(
        "rust", (".rs",),
        defs={"function_item": "function", "struct_item": "class", "enum_item": "type",
              "trait_item": "interface", "mod_item": "module", "type_item": "type"},
        calls={"call_expression": "function", "macro_invocation": "macro"},
        imports=("use_declaration",),
        branches=("if_expression", "for_expression", "while_expression", "loop_expression",
                  "match_arm"),
    ),
    "c": LangSpec(
        "c", (".c", ".h"),
        defs={"function_definition": "function", "struct_specifier": "class",
              "enum_specifier": "type"},
        calls={"call_expression": "function"},
        imports=("preproc_include",),
        branches=_C_BRANCHES,
    ),
    "cpp": LangSpec(
        "cpp", (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"),
        defs={"function_definition": "function", "class_specifier": "class",
              "struct_specifier": "class", "namespace_definition": "module"},
        calls={"call_expression": "function"},
        imports=("preproc_include",),
        branches=_C_BRANCHES + ("for_range_loop",),
    ),
    "csharp": LangSpec(
        "csharp", (".cs",),
        defs={"class_declaration": "class", "interface_declaration": "interface",
              "struct_declaration": "class", "record_declaration": "class",
              "enum_declaration": "type", "method_declaration": "method",
              "constructor_declaration": "method"},
        calls={"invocation_expression": "function", "object_creation_expression": "type"},
        imports=("using_directive",),
        branches=_C_BRANCHES + ("switch_section", "foreach_statement"),
        containers=("class_declaration", "struct_declaration", "interface_declaration"),
    ),
    "ruby": LangSpec(
        "ruby", (".rb",),
        defs={"method": "method", "singleton_method": "method", "class": "class",
              "module": "module"},
        calls={"call": "method"},
        imports=(),
        branches=("if", "elsif", "unless", "while", "until", "for", "when", "rescue",
                  "conditional"),
        containers=("class", "module"),
    ),
    "php": LangSpec(
        "php", (".php",),
        defs={"function_definition": "function", "method_declaration": "method",
              "class_declaration": "class", "interface_declaration": "interface",
              "trait_declaration": "class"},
        calls={"function_call_expression": "function", "member_call_expression": "name",
               "scoped_call_expression": "name", "object_creation_expression": None},
        imports=("namespace_use_declaration",),
        branches=("if_statement", "else_if_clause", "for_statement", "foreach_statement",
                  "while_statement", "case_statement", "catch_clause",
                  "conditional_expression"),
        containers=("class_declaration",),
    ),
    "scala": LangSpec(
        "scala", (".scala",),
        defs={"class_definition": "class", "object_definition": "class",
              "trait_definition": "interface", "function_definition": "function"},
        calls={"call_expression": "function"},
        imports=("import_declaration",),
        branches=("if_expression", "for_expression", "while_expression", "case_clause"),
    ),
    "swift": LangSpec(
        "swift", (".swift",),
        defs={"class_declaration": "class", "protocol_declaration": "interface",
              "function_declaration": "function"},
        calls={"call_expression": None},
        imports=("import_declaration",),
        branches=("if_statement", "for_statement", "while_statement", "switch_entry",
                  "catch_block", "guard_statement"),
    ),
}

# Plain-text formats that are indexed lexically (chunked by lines) but not parsed.
TEXT_EXTS = {
    ".md": "markdown", ".rst": "rst", ".txt": "text", ".toml": "toml", ".yaml": "yaml",
    ".yml": "yaml", ".json": "json", ".cfg": "ini", ".ini": "ini", ".sql": "sql",
    ".sh": "bash", ".html": "html", ".css": "css", ".scss": "css", ".vue": "vue",
    ".svelte": "svelte", ".proto": "proto", ".graphql": "graphql", ".tf": "hcl",
    ".dockerfile": "dockerfile", ".gradle": "gradle", ".xml": "xml", ".lua": "lua",
    ".dart": "dart", ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".hs": "haskell",
    ".ml": "ocaml", ".r": "r", ".jl": "julia", ".zig": "zig", ".nim": "nim",
}
TEXT_NAMES = {"Dockerfile": "dockerfile", "Makefile": "make", "README": "markdown"}

EXT_TO_LANG: dict[str, str] = {e: spec.name for spec in LANGS.values() for e in spec.exts}

# Tree-sitter grammar names differ from ours in a few cases.
GRAMMAR = {"csharp": "csharp"}


def detect(path: str) -> tuple[str | None, bool]:
    """Return (language, parsed) for a path; parsed is False for text-only formats."""
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot >= 0 else ""
    if ext in EXT_TO_LANG:
        return EXT_TO_LANG[ext], True
    if ext in TEXT_EXTS:
        return TEXT_EXTS[ext], False
    for prefix, lang in TEXT_NAMES.items():
        if name.startswith(prefix):
            return lang, False
    return None, False


_TEST_DIR_PARTS = ("/test/", "/tests/", "/__tests__/", "/spec/", "/testing/", "/src/test/")


def is_test_path(path: str) -> bool:
    p = "/" + path.lower()
    name = p.rsplit("/", 1)[-1]
    if any(part in p for part in _TEST_DIR_PARTS):
        return True
    return (
        name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go")
        or ".test." in name or ".spec." in name or name.endswith("test.java")
        or name.endswith("tests.cs") or name.endswith("_spec.rb") or name == "conftest.py"
    )
