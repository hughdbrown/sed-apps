#!/usr/bin/env python

from sys import exit
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
    \(.*\):$
""", re.VERBOSE)

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


# Find python function definitions
#   def func_name(args):
# -----
# Replace with function definition followed by logger call
class StreamEditorInsertDebugAfterDef(StreamEditor):
    table = [
        [[HAS_LOGGER, NEXT], ],
        [[DEF_FUNC, REPEAT], ],
    ]

    def apply_match(self, i, dict_matches):
        LOGGER.debug(dict_matches)
        fmt = "{0[indent]}    {1}.debug('{0[func_name]}')"
        matches = dict_matches["matches"]
        fns = [match for match in matches if match.get('func_name')]
        logger = [match for match in matches if match.get("name")]
        assert len(logger) == 1
        logger_name = logger[0]["name"]

        for match in sorted(fns, key=itemgetter('line_no'), reverse=True):
            # {'func_name': '__init__', 'line_no': 41, 'indent': '    '}
            LOGGER.debug(match)
            s = fmt.format(match, logger_name)
            self.append_range(match["line_no"], [s])


def main():
    return call_main(StreamEditorInsertDebugAfterDef)


if __name__ == '__main__':
    exit(main())

