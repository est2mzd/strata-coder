"""Python-only structural retrieval, inspired by progressive disclosure.

This is an AST index, not a language server: it does not resolve references.
No project code is imported or executed. Callers enforce path permissions.
"""
import ast
import hashlib


def retrieve(source, *, symbol='', offset=0, expected_sha256=''):
    sha = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if expected_sha256 and expected_sha256 != sha:
        raise ValueError('Stale context hash; obtain a fresh overview')
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError) as e:
        raise ValueError('Python parsing failed; use bounded read_file') from e
    entries = []
    def visit(node, parent=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = parent + '.' + child.name if parent else child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                entries.append({'symbol':name, 'kind':type(child).__name__,
                                'start_line':start, 'end_line':child.end_lineno})
                visit(child, name)
            else:
                visit(child, parent)
    try:
        visit(tree)
    except RecursionError as e:
        raise ValueError('Python nesting too deep; use bounded read_file') from e
    if not symbol:
        page = entries[offset:offset + 50]
        return {'sha256':sha, 'symbols':page, 'total_symbols':len(entries),
                'next_offset':offset + len(page) if offset + len(page) < len(entries) else None,
                'note':'AST definitions only. Imports, module statements and references require separate inspection.'}
    matches = [e for e in entries if e['symbol'] == symbol]
    if len(matches) != 1:
        raise ValueError('Symbol absent or ambiguous; inspect file context')
    entry = matches[0]
    lines = source.splitlines(keepends=True)
    body = ''.join(lines[entry['start_line'] - 1:entry['end_line']])
    content = body[offset:offset + 6000]
    return {'sha256':sha, **entry, 'content':content, 'offset':offset,
            'total_chars':len(body),
            'next_offset':offset + len(content) if offset + len(content) < len(body) else None}
