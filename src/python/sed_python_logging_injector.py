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
    REPEAT, NEXT, ACCEPT,
    ANY,
)

REG_IMPORT = re.compile(r"""
    ^import\s+
    (?P<library>[\w\d_\.]+)
    .*
    $
""", re.VERBOSE)

FROM_IMPORT = re.compile(r"""
    ^from\s+
    (?P<library>[\w\d_\.]+)\s
    import\s
    (?P<imports>[\w\d_\.]+(,\s+[\w\d_\.]+)*)
    .*$
""", re.VERBOSE)

HAS_HASH_BANG = re.compile(r"""
    ^(?P<hashbang>\#!)
    .*$
""", re.VERBOSE)

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


# pylint: disable=too-few-public-methods
# StreamEditor class has a minimal interface that a derived
# class must implement, so pylint is cranky about the number of
# methods implemented. Silence this warning.

# Find place to inject `import logging`
class StreamEditorInjectLogging(StreamEditor):
    """
    Implement class for inserting logging imports into a python file.
    """
    table = [
        [[FROM_IMPORT, NEXT], [REG_IMPORT, NEXT], ],
        [[FROM_IMPORT, REPEAT], [REG_IMPORT, REPEAT], [ANY, ACCEPT], ],
    ]

    def apply_match(self, _, dict_matches):
        """
        Implement the `apply_match` method to the file.
        """
        LOGGER.debug(dict_matches)
        matches = dict_matches["matches"]
        libraries = [m for m in matches if 'library' in m]

        # Not strictly a good assertion, but I am not handling python code
        # that has no imports.
        assert libraries

        # If `logging` not already imported, add it.
        if not any('logging' == m['library'] for m in libraries):
            match = libraries[-1]
            match_line = match["line_no"]
            insert_str = "import logging\n\nlogger = logging.getLogger(__name__)"
            self.insert_range(match_line, [insert_str])


def main():
    """ Main entry point"""
    return call_main(StreamEditorInjectLogging)


if __name__ == '__main__':
    sys.exit(main())
