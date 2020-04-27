# -*- coding: utf-8 -*-
from __future__ import annotations
import ast


class GetHyperEdgeNames(ast.NodeVisitor):
    def __init__(self):
        self.lval_name_set = set()
        self.rval_name_set = set()
        self.to_add_set = self.rval_name_set

    def __call__(self, node):
        self.visit(node)
        return self.lval_name_set, self.rval_name_set

    def visit_Name(self, node):
        self.to_add_set.add(node.id)

    def visit_Subscript(self, node):
        # TODO: add slice to rval set
        self.visit(node.value)

    def visit_Assign(self, node):
        self.to_add_set = self.lval_name_set
        for target in node.targets:
            self.visit(target)
        self.to_add_set = self.rval_name_set
        self.visit(node.value)

    def visit_AugAssign(self, node):
        self.to_add_set = self.lval_name_set
        self.visit(node.target)
        self.to_add_set = self.rval_name_set
        self.visit(node.value)

    def visit_For(self, node):
        # skip body -- will have dummy since this visitor works line-by-line
        self.to_add_set = self.lval_name_set
        self.visit(node.target)
        self.to_add_set = self.rval_name_set
        self.visit(node.iter)

    def visit_FunctionDef(self, node):
        self.lval_name_set.add(node.name)
        self.to_add_set = self.rval_name_set
        self.visit(node.args)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_Lambda(self, node):
        # remove node.arguments
        self.visit(node.body)
        self.visit(node.args)
        old = self.rval_name_set
        self.rval_name_set = set()
        # throw away anything appearing in lambda body that isn't bound
        self.visit(node.args.args)
        self.visit(node.args.vararg)
        self.visit(node.args.kwonlyargs)
        self.visit(node.args.kwarg)
        self.rval_name_set = old - self.rval_name_set

    def generic_visit(self, node):
        if node is None:
            return
        elif isinstance(node, list):
            for item in node:
                self.visit(item)
        else:
            super().generic_visit(node)

    def visit_arguments(self, node):
        # skip over unbound args
        self.visit(node.defaults)
        self.visit(node.kw_defaults)

    def visit_arg(self, node):
        self.rval_name_set.add(node.arg)


def get_hyperedge_lvals_and_rvals(node: ast.AST):
    return GetHyperEdgeNames()(node)