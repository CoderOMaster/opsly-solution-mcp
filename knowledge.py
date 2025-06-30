import os
import ast
import textwrap
from pathlib import Path
from tqdm import tqdm
from connections.neo4j_login import connect_to_neo4j

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

# (1) Where your normalized repositories live:
NORMALIZED_BASE = Path("normalized_repos")

connect_to_neo4j()
# ─── HELPERS FOR AST PARSING ───────────────────────────────────────────────────

def get_module_name(repo_root: Path, file_path: Path) -> str:
    """
    Given:
      repo_root = normalized_repos/repoA
      file_path = normalized_repos/repoA/subpkg/helper.py
    Return the Python module string: "repoA.subpkg.helper"
    """
    rel = file_path.relative_to(repo_root).with_suffix("")  # e.g. subpkg/helper
    parts = [repo_root.name] + list(rel.parts)             # ["repoA", "subpkg", "helper"]
    return ".".join(parts)

def collect_python_files(normalized_base: Path):
    """
    Walk through each repo folder in `normalized_base` and return a list of tuples:
      [
        (repo_name(str), file_path(Path), module_name(str)), 
        ...
      ]
    """
    all_files = []
    for repo_dir in normalized_base.iterdir():
        if not repo_dir.is_dir():
            continue
        repo_name = repo_dir.name
        for root, _, files in os.walk(repo_dir):
            root_path = Path(root)
            for fname in files:
                if fname.lower().endswith(".py"):
                    fpath = root_path / fname
                    module_name = get_module_name(repo_dir, fpath)
                    all_files.append((repo_name, fpath, module_name))
    return all_files

def parse_defs_and_imports(file_path: Path):
    """
    Parse a .py file and return three lists/dicts:
      - functions:   { func_name: ast.FunctionDef node }
      - classes:     { class_name: ast.ClassDef node }
      - imports:     [ (imported_module_str, lineno) , ... ]  
                      e.g. if file has `import subpkg.helper as h`, record ("subpkg.helper", lineno)
                      or  if file has `from subpkg.foo import bar`, record ("subpkg.foo.bar", lineno)
    """
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=str(file_path))
    funcs = {}
    classes = {}
    imports = []

    # Use ast.get_source_segment for precise code extraction (Python 3.8+)
    # For older versions, you might need to manually handle lines.
    try:
        from ast import get_source_segment
    except ImportError:
        get_source_segment = lambda source, node: "[Code extraction requires Python 3.8+]"

    

    for node in ast.walk(tree):
        # ─── Collect function defs ────────────────────────────────────────────────
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = {
                "node": node,
                "code": textwrap.dedent(get_source_segment(source, node))
            }

        # ─── Collect class defs ───────────────────────────────────────────────────
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = {
                "node": node,
                "code": textwrap.dedent(get_source_segment(source, node))
            }

        # ─── Collect import statements ────────────────────────────────────────────
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # e.g. "import subpkg.helper as h" → record "subpkg.helper"
                imports.append((alias.name, node.lineno))

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                # e.g. "from subpkg import helper" → record "subpkg.helper"
                full_name = f"{module}.{alias.name}" if module else alias.name
                imports.append((full_name, node.lineno))

    return funcs, classes, imports

def collect_call_edges(func_node: ast.FunctionDef):
    """
    Given an ast.FunctionDef, collect all simple calls of the form:
      foo(...)
    or
      self.foo(...)
    This returns a set of call-names (strings). We’ll only link a CALLS edge
    if we later find that name in the same file’s function map.
    """
    calls = set()

    class _CallVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            # If it’s a bare name, e.g. foo(...)
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            # If it’s an attribute, e.g. self.foo(...)
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.attr, str):
                    calls.add(node.func.attr)
            self.generic_visit(node)

    _CallVisitor().visit(func_node)
    return calls

def collect_inheritance_edges(class_node: ast.ClassDef):
    """
    For a ClassDef, return a list of parent‐class-names (strings). Only simple names:
      class Child(ParentA, ParentB): ...
    or
      class Child(module.ParentC): ...
    We’ll try to link “INHERITS” to any Class in our graph with a matching name.
    """
    bases = []
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)  # e.g. ParentA
        elif isinstance(base, ast.Attribute):
            # e.g. module.ParentC
            name_parts = []
            cur = base
            while isinstance(cur, ast.Attribute):
                name_parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                name_parts.append(cur.id)
                full = ".".join(reversed(name_parts))
                bases.append(full)
        # other complexities (e.g. subscripts, calls) are skipped
    return bases

# ─── BUILD A REPO‐WIDE INDEX MAPS FOR RESOLUTION ───────────────────────────────

def build_repo_index(all_files):
    """
    From the list of all_files = [(repo_name, Path, module_name), ...], build:
      - module_to_file: { "repoA.subpkg.helper": Path(...) }
      - file_to_module: { Path(...): "repoA.subpkg.helper" }
    """
    module_to_file = {}
    file_to_module = {}
    for repo_name, fpath, module_name in all_files:
        module_to_file[module_name] = fpath
        file_to_module[fpath] = module_name
    return module_to_file, file_to_module

# ─── NEO4J WRAPPER ────────────────────────────────────────────────────────────

class Neo4jGraphBuilder:
    def __init__(self):
        self.driver = connect_to_neo4j()

    def close(self):
        self.driver.close()

    def run(self, query: str, params: dict = None, return_results: bool = False):
        with self.driver.session() as sess:
            if params:
                result = sess.run(query, params)
            else:
                result = sess.run(query)
            if return_results:
                return list(result)

    def clear_database(self):
        """ Deletes all nodes and relationships from the graph. """
        print("Clearing the database...")
        self.run("MATCH (n) DETACH DELETE n")

    def create_repo_node(self, repo_name: str):
        """
        MERGE (r:Repo {name: $repo_name})
        """
        self.run(
            """
            MERGE (r:Repo {name: $repo_name})
            """,
            {"repo_name": repo_name}
        )

    def create_file_node(self, repo_name: str, file_path: str, module_name: str):
        self.run(
            """
            MATCH (r:Repo {name: $repo_name})
            MERGE (f:File {path: $file_path})
            ON CREATE SET f.module = $module_name, f.repo = $repo_name
            MERGE (r)-[:CONTAINS]->(f)
            """,
            {
                "repo_name": repo_name,
                "file_path": file_path,
                "module_name": module_name,
            },
        )

    def create_function_node(self, repo_name: str, file_path: str, module_name: str, func_name: str, lineno: int, code: str):
        qualified_name = f"{module_name}.{func_name}"
        self.run(
            """
            MERGE (fn:Function {qualified_name: $qualified_name})
            ON CREATE SET
                fn.name = $func_name,
                fn.lineno = $lineno,
                fn.file = $file_path,
                fn.repo = $repo_name,
                fn.code = $code
            ON MATCH SET
                fn.code = $code
            WITH fn
            MATCH (f:File {path: $file_path})
            MERGE (f)-[:DECLARES_FUNCTION]->(fn)
            """,
            {
                "qualified_name": qualified_name,
                "func_name": func_name,
                "lineno": lineno,
                "file_path": file_path,
                "repo_name": repo_name,
                "code": code
            }
        )

    def create_class_node(self, repo_name: str, file_path: str, module_name: str, class_name: str, lineno: int, code: str):
        qualified_name = f"{module_name}.{class_name}"
        self.run(
            """
            MERGE (cl:Class {qualified_name: $qualified_name})
            ON CREATE SET
                cl.name = $class_name,
                cl.lineno = $lineno,
                cl.file = $file_path,
                cl.repo = $repo_name,
                cl.code = $code
            ON MATCH SET
                cl.code = $code
            WITH cl
            MATCH (f:File {path: $file_path})
            MERGE (f)-[:DECLARES_CLASS]->(cl)
            """,
            {
                "qualified_name": qualified_name,
                "class_name": class_name,
                "lineno": lineno,
                "file_path": file_path,
                "repo_name": repo_name,
                "code": code
            }
        )

    def create_import_edge(self, from_file: str, to_file: str):
        """
        MATCH (src:File {path: $from_file}), (dst:File {path: $to_file})
        MERGE (src)-[:IMPORTS]->(dst)
        """
        self.run(
            """
            MATCH (src:File {path: $from_file}), (dst:File {path: $to_file})
            MERGE (src)-[:IMPORTS]->(dst)
            """,
            {"from_file": from_file, "to_file": to_file}
        )

    def create_call_edge(self, from_func: str, to_func: str):
        """
        MATCH (f1:Function {qualified_name: $from_func}), (f2:Function {qualified_name: $to_func})
        MERGE (f1)-[:CALLS]->(f2)
        """
        self.run(
            """
            MATCH (f1:Function {qualified_name: $from_func}), (f2:Function {qualified_name: $to_func})
            MERGE (f1)-[:CALLS]->(f2)
            """,
            {"from_func": from_func, "to_func": to_func}
        )

    def create_inherits_edge(self, child_cls: str, parent_cls: str):
        """
        MATCH (c:Class {qualified_name: $child_cls}), (p:Class {qualified_name: $parent_cls})
        MERGE (c)-[:INHERITS]->(p)
        """
        self.run(
            """
            MATCH (c:Class {qualified_name: $child_cls}), (p:Class {qualified_name: $parent_cls})
            MERGE (c)-[:INHERITS]->(p)
            """,
            {"child_cls": child_cls, "parent_cls": parent_cls}
        )

    def create_external_import_edge(self, from_file: str, external_module: str):
        self.run(
            """
            MERGE (ext:ExternalModule {name: $external_module})
            WITH ext
            MATCH (src:File {path: $from_file})
            MERGE (src)-[:IMPORTS]->(ext)
            """,
            {"from_file": from_file, "external_module": external_module},
        )

# ─── MAIN EXECUTION ───────────────────────────────────────────────────────────

def main():
    """ Main pipeline to build the graph """
    print("Starting knowledge graph build...")
    graph = Neo4jGraphBuilder()
    graph.clear_database()  # Start with a clean slate
    
    # 1. Find all Python files and create Repo and File nodes
    print("Pass 1: Finding Python files and creating Repo/File nodes...")
    all_files = collect_python_files(NORMALIZED_BASE)
    for repo_name, fpath, module_name in tqdm(all_files, desc="Files"):
        graph.create_repo_node(repo_name)
        graph.create_file_node(repo_name, str(fpath), module_name)

    # 2. Build repo-wide index for resolving imports
    module_to_file, file_to_module = build_repo_index(all_files)
    all_repo_modules = set(module_to_file.keys())

    # 3. Parse each file to create Function and Class nodes
    print("\nPass 2: Parsing files for functions, classes, and imports...")
    parsed_files = {}
    for repo_name, fpath, module_name in tqdm(all_files, desc="Parsing"):
        try:
            funcs, classes, imports = parse_defs_and_imports(fpath)
            parsed_files[str(fpath)] = {
                "funcs": funcs,
                "classes": classes,
                "imports": imports,
                "module": module_name,
            }
            # Create nodes
            for func_name, func_data in funcs.items():
                graph.create_function_node(
                    repo_name, str(fpath), module_name, func_name, func_data["node"].lineno, func_data["code"]
                )
            for class_name, class_data in classes.items():
                graph.create_class_node(
                    repo_name, str(fpath), module_name, class_name, class_data["node"].lineno, class_data["code"]
                )
        except Exception as e:
            print(f"\n[ERROR] Could not parse {fpath}: {e}")

    # 4. Create edges (CALLS, IMPORTS, INHERITS)
    print("\nPass 3: Creating relationships (CALLS, IMPORTS, INHERITS)...")
    for fpath_str, data in tqdm(parsed_files.items(), desc="Linking"):
        # IMPORTS edges
        for imp_name, _ in data["imports"]:
            # Try to resolve internal imports
            if imp_name in module_to_file:
                graph.create_import_edge(fpath_str, str(module_to_file[imp_name]))
            else:
                # Simplified external import check
                if not imp_name.startswith(data["module"].split('.')[0]):
                    graph.create_external_import_edge(fpath_str, imp_name)

        # CALLS edges
        for func_name, func_data in data["funcs"].items():
            from_func_fqn = f"{data['module']}.{func_name}"
            calls = collect_call_edges(func_data["node"])
            for call_name in calls:
                # Check for calls to other functions in the same file
                if call_name in data["funcs"]:
                    to_func_fqn = f"{data['module']}.{call_name}"
                    graph.create_call_edge(from_func_fqn, to_func_fqn)

        # INHERITS edges
        for class_name, class_data in data["classes"].items():
            child_cls_fqn = f"{data['module']}.{class_name}"
            bases = collect_inheritance_edges(class_data["node"])
            for base_name in bases:
                # For simplicity, we only resolve inheritance within the same repo
                # A full solution would check imports for FQNs
                if base_name in all_repo_modules:
                     graph.create_inherits_edge(child_cls_fqn, base_name)


    print("\nKnowledge graph build complete!")
    graph.close()

if __name__ == "__main__":
    main()