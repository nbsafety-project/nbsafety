# -*- coding: utf-8 -*-
import ast
import logging
from typing import cast, TYPE_CHECKING

from nbsafety.tracing.trace_events import TraceEvent

if TYPE_CHECKING:
    from typing import Dict, List, Optional, Set, Tuple
    from types import FrameType
    from nbsafety.data_model.scope import NamespaceScope
    from nbsafety.tracing.trace_stmt import TraceStatement
    from nbsafety.safety import NotebookSafety

logger = logging.getLogger(__name__)


class TraceState(object):
    def __init__(self, safety: 'NotebookSafety'):
        self.safety = safety
        self.cur_frame_scope = safety.global_scope
        self.prev_trace_stmt_in_cur_frame: Optional[TraceStatement] = None
        self.inside_lambda = False
        self.call_depth = 0
        self.traced_statements: Dict[int, TraceStatement] = {}
        self.stack: List[Tuple[TraceStatement, bool]] = []
        self.source: Optional[str] = None
        self.prev_trace_stmt: Optional[TraceStatement] = None
        self.prev_event: Optional[TraceEvent] = None
        self.cur_cell_position_idx = -1
        self.error_occurred = False
        self.tracing_enabled = False
        self.tracing_reset_pending = False

    def _check_prev_stmt_done_executing_hook(self, event: 'TraceEvent', trace_stmt: 'TraceStatement'):
        if event not in (
                TraceEvent.line, TraceEvent.return_
        ) or self.prev_event in (
                TraceEvent.call, TraceEvent.exception
        ):
            return

        if event == TraceEvent.return_:
            prev_overall = self.prev_trace_stmt
            if prev_overall is not None and prev_overall is not self.stack[-1][0]:
                # this condition ensures we're not inside of a stmt with multiple calls (such as map w/ lambda)
                prev_overall.finished_execution_hook()
            return

        # we'll be needing this
        prev_this_frame = self.prev_trace_stmt_in_cur_frame

        if prev_this_frame is None or prev_this_frame.finished:
            return

        if isinstance(prev_this_frame.stmt_node, ast.ClassDef):
            # classdefs are not finished until we reach the end of the class body
            # we handle these with special logic
            if self.prev_event == TraceEvent.return_:
                if event == TraceEvent.line or prev_this_frame is not trace_stmt:
                    # NOTE: in Python >= 3.8, it seems that prev_this_frame and trace_stmt would always point to the
                    # same things due to how tracing is implemented, but we cannot rely on that for Python < 3.7
                    prev_this_frame.finished_execution_hook()
        elif prev_this_frame is not trace_stmt:
            prev_this_frame.finished_execution_hook()

    def _handle_call_transition(self, trace_stmt: 'TraceStatement'):
        # TODO: figure out a better way to determine if we're inside a lambda
        #  could this one lead to a false negative if a lambda is in the default of a function def kwarg?
        inside_lambda = not isinstance(trace_stmt.stmt_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        self.stack.append((self.prev_trace_stmt_in_cur_frame, self.inside_lambda))
        self.inside_lambda = inside_lambda
        self.cur_frame_scope = trace_stmt.get_post_call_scope(self.cur_frame_scope)
        logger.debug('entering scope %s', self.cur_frame_scope)
        self.prev_trace_stmt_in_cur_frame = None
        self.safety.attr_trace_manager.push_stack(self.cur_frame_scope)

    def _handle_return_transition(self, trace_stmt: 'TraceStatement'):
        logger.debug('leaving scope %s', self.cur_frame_scope)
        return_to_stmt, return_to_inside_lambda = self.stack.pop()
        assert return_to_stmt is not None
        if self.prev_event != TraceEvent.exception:
            # exception events are followed by return events until we hit an except clause
            # no need to track dependencies in this case
            if isinstance(return_to_stmt.stmt_node, ast.ClassDef):
                return_to_stmt.class_scope = cast('NamespaceScope', self.cur_frame_scope)
            elif isinstance(trace_stmt.stmt_node, ast.Return) or self.inside_lambda:
                if not trace_stmt.lambda_call_point_deps_done_once:
                    trace_stmt.lambda_call_point_deps_done_once = True
                    return_to_stmt.call_point_deps.append(trace_stmt.compute_rval_dependencies())
        self.inside_lambda = return_to_inside_lambda
        # reset for the previous frame, so that we push it again if it has another funcall
        self.prev_trace_stmt_in_cur_frame = return_to_stmt
        # self.cur_frame_scope = return_to_stmt.scope
        self.safety.attr_trace_manager.pop_stack()
        self.cur_frame_scope = self.safety.attr_trace_manager.active_scope
        logger.debug('entering scope %s', self.cur_frame_scope)

    def state_transition_hook(
            self,
            event: 'TraceEvent',
            trace_stmt: 'TraceStatement'
    ):
        self.safety.trace_event_counter[0] += 1

        self._check_prev_stmt_done_executing_hook(event, trace_stmt)

        self.prev_trace_stmt = trace_stmt
        if event == TraceEvent.line:
            self.prev_trace_stmt_in_cur_frame = trace_stmt
        if event == TraceEvent.call:
            self._handle_call_transition(trace_stmt)
        if event == TraceEvent.return_:
            self._handle_return_transition(trace_stmt)
        self.prev_event = event

    @staticmethod
    def get_position(frame: 'FrameType'):
        cell_num = int(frame.f_code.co_filename.split('-')[2])
        return cell_num, frame.f_lineno
