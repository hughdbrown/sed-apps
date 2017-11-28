#!/usr/bin/env python
"""
Streaming editor for modifying python files
This script uses the `sed` python package to programmatically
inject decorators at the head of function definitions.
"""
import sys
import re
from operator import itemgetter
import logging

from sed.engine import (
    StreamEditor,
    call_main,
    REPEAT, NEXT
)

HAS_LOGGER = re.compile(r"""
    ^(?P<name>[\d\w_]+)
    \s*\=\s*
    (logging\.)?
    getLogger.*$
""", re.VERBOSE)

DEF_FUNC = re.compile(r"""
    ^(?P<indent>\s*)
    def\s+
    (?P<func_name>[\d\w_]+)
    .*$
""", re.VERBOSE)

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


# pylint: disable=too-few-public-methods
# StreamEditor class has a minimal interface that a derived
# class must implement, so pylint is cranky about the number of
# methods implemented. Silence this warning.

# Find python function definitions
#   def func_name(args):
# -----
# Replace with function definition followed by logger call
class StreamEditorInsertDebugAfterDef(StreamEditor):
    """
    Implement class for inserting debugging statements into a python file.
    (Reimplemented to use decorators on methods.)
    """
    table = [
        [[HAS_LOGGER, NEXT], ],
        [[DEF_FUNC, REPEAT], ],
    ]

    def apply_match(self, _, dict_matches):
        """
        Implement the `apply_match` method to the file.
        """
        def has_module(lines, match_line):
            """
            Check if a function definition that starts at line `match_line`
            will have the __module__ attribute when decorated.

            Some functions cannot be decorated because they are
            missing relevant function attributes. Functions decorated
            with @staticmethod and @classmethod are two of them.
            """
            prev_line = lines[match_line - 1]
            return not prev_line.lstrip().startswith(
                ("@staticmethod", "@classmethod")
            )

        LOGGER.debug(dict_matches)
        matches = dict_matches["matches"]
        fns = [match for match in matches if match.get('func_name')]
        logger = [match for match in matches if match.get("name")]
        assert len(logger) == 1

        for match in sorted(fns, key=itemgetter('line_no'), reverse=True):
            # {'func_name': '__init__', 'line_no': 41, 'indent': '    '}
            LOGGER.debug(match)
            match_line = match["line_no"]
            if has_module(self.lines, match_line):
                insert_str = "{0[indent]}@func_inspect".format(match)
                self.insert_range(match_line, [insert_str])

        # If you do this first, then all the lines will be off in
        # the function-name matches above.
        logger = logger[0]
        logger_line = logger["line_no"]
        insert_str = "from MMApp.decorators import func_inspect"
        self.insert_range(logger_line, [insert_str])

def main():
    """ Main entry point"""
    return call_main(StreamEditorInsertDebugAfterDef)


if __name__ == '__main__':
    sys.exit(main())
