import ast


class StatementInserter(ast.NodeTransformer):
    def __init__(self, insert_stmt_template: str, cell_counter: int):
        self._insert_stmt_template = insert_stmt_template
        self._cell_counter = cell_counter
        self._cur_line_id = 0

    def _get_parsed_insert_stmt(self):
        ret = ast.parse(self._insert_stmt_template.format(site_id=(self._cell_counter, self._cur_line_id))).body[0]
        self._cur_line_id += 1
        return ret

    def visit(self, node):
        if hasattr(node, 'handlers'):
            new_handlers = []
            for handler in node.handlers:
                new_handlers.append(self.visit(handler))
            node.handlers = new_handlers
        if not hasattr(node, 'body'):
            return node
        if not all(isinstance(nd, ast.stmt) for nd in node.body):
            return node
        new_stmts = []
        for stmt in node.body:
            insert_stmt = self._get_parsed_insert_stmt()
            ast.copy_location(insert_stmt, stmt)
            new_stmts.append(insert_stmt)
            new_stmts.append(self.visit(stmt))
        node.body = new_stmts
        return node