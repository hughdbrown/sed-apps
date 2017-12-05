#!/usr/bin/env python
"""
Streaming editor for modifying python files
This script uses the `sed` python package to programmatically
inject decorators at the head of function definitions.
"""
from __future__ import print_function

import os.path
import sys
import re
import logging
from collections import namedtuple, Counter
from operator import attrgetter

from sed.engine import (
    StreamEditor,
    call_main,
    REPEAT, NEXT, CUT,
)

MODULE_NAME = re.compile(r"""
    ^\*+\s
    Module\s+
    (?P<filename>[\w\d\._-]+)
    $
""", re.VERBOSE)

FROM_IMP = re.compile(r"""
    ^
    from
    \s+(?P<library>[\w\d_\.]+)
    \s+import
    \s+(?P<imports>[\w\d_\.,\s]+)
    $
""", re.VERBOSE)

#C: 75, 0: Unnecessary parens after 'print' keyword (superfluous-parens)
PYLINT_ITEM = re.compile(r"""
    ^
    (?P<type>[ERCW])
    :\s*
    (?P<where1>\d+)
    ,\s*
    (?P<where2>-?\d+)
    :\s+
    (?P<desc>.*?)
    \(
    (?P<error>[\w_\.-]+)
    \)
    $
""", re.VERBOSE)


# pylint: disable=logging-format-interpolation
logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


Item = namedtuple("Item", ["type", "line_no", "line_offset", "desc", "error"])
def item_maker(match):
    """ Helper function for making an Item from a dict """
    return Item(
        match["type"],
        int(match["where1"]) - 1,
        int(match["where2"]),
        match["desc"],
        match["error"]
    )


def find_string(s):
    result = next((i, c) for i, c in enumerate(s) if c in ('"', "'"))
    if result is not None:
        start, quote_char = result
        end = next(
            i for i, c in enumerate(s[start + 1: ])
            if c == quote_char and s[i - 1] != '\\'
        )
        if end is not None:
            return (start, start + end + 1)
    return None, None


class DerivedStreamEditor(StreamEditor):
    """
    Simple derived class to allow simple stream-editing.
    """
    table = [None]
    def apply_match(self, *_):  # pylint: disable=arguments-differ
        """ Required method for StreamEditor """
        pass

class EditorOptions(object):
    """ Hack: make an object to initialize StreamEditor """
    def __init__(self):
        self.verbose = True
        self.ext = None
        self.new_ext = None
        self.dryrun = False


def get_indent(src):
    """ Helper function to get the leading whitespace from a line """
    match = re.match(r"^(\s*)(.*)$", src)
    return match.group(1), match.group(2)


def bad_whitespace(editor, item):
    """ Pylint method to fix bad-whitespace error """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    LOGGER.info(error_text)
    if item.desc == "No space allowed around keyword argument assignment":
        editor.lines[line_no] = re.sub(r"\s+=\s+", error_text, "=")
    elif item.desc == "Exactly one space required after comma":
        editor.lines[line_no] = re.sub(r"\s+,\s+", error_text, ", ")


def bad_continuation(*_):
    """ Pylint method to fix bad-continuation error """
    pass


def trailing_newline(editor, item):
    """ Pylint method to fix trailing-newline error """
    line_no = item.line_no
    loc = (
        next(
            x for x in reversed(range(line_no, len(editor.lines)))
             if not re.match(r'^\s*$', editor.lines[x])
        ) or line_no,
        len(editor.lines)
    )
    editor.delete_range(loc)


def no_self_use(editor, item):
    """ Pylint method to fix no_self_use error """
    line_no = item.line_no
    LOGGER.info("no_self_use: {0}".format(line_no))
    error_text = editor.lines[line_no]
    LOGGER.info(error_text)
    indent, _ = get_indent(error_text)
    editor.lines[line_no] = error_text.replace("self, ", "").replace("(self)", "()")
    editor.insert_range(line_no, ["{0}@staticmethod".format(indent)])


def no_value_for_parameter(*_):
    """ Pylint method to fix no_value_for_parameter error """
    pass


def superfluous_parens(*_):
    """ Pylint method to fix superfluous_parens error """
    pass


def missing_docstring(editor, item):
    """ Pylint method to fix missing_docstring error """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    indent, rest = get_indent(error_text)
    if not rest.startswith(("def ", "class ")):
        func = editor.insert_range
        docstring = '""" Pro forma module docstring """'
    else:
        func = editor.append_range
        fmt = (
            '{0}""" Pro forma function/method docstring """' if rest.startswith("def ")
            else '{0}""" Pro forma class docstring """'
        )
        docstring = fmt.format(indent + "    ")
        for x in range(10):
            if "):" in editor.lines[line_no + x]:
                line_no += x
                break
        else:
            # If we cannot find where a function/class definition ends
            # in reasonable time, give up.
            return
    func(line_no, [docstring])


def invalid_name(*_):
    """ Pylint method to fix invalid_name error """
    pass


def unused_import(editor, item):
    """ Pylint method to fix unused_import error """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    remove = item.desc.split(' ')[1]
    m = FROM_IMP.match(error_text)
    if m:
        groups = m.groupdict()
        library = groups["library"]
        imports = [imp.strip() for imp in groups["imports"].split(',')]
        repaired_line = "from {0} import {1}".format(
            library,
            ", ".join(sorted(set(imports) - set([remove])))
        )
        loc = (line_no, line_no + 1)
        editor.replace_range(loc, [repaired_line])
    return (line_no, 0)


def misplaced_comparison_constant(*_):
    """ Pylint method to fix misplaced_comparison_constant error """
    pass


def len_as_condition(editor, item):
    """ Pylint method to fix len-as-condition error """
    zero_cmp = re.compile(r'''
        ^(?P<left>.*?)
        len\((?P<len>.*?)\)
        \s+==\s+0
        (?P<right>.*)$
    ''', re.VERBOSE)
    nzero_cmp = re.compile(r'''
        ^(?P<left>.*?)
        len\((?P<len>.*?)\)
        \s+!=\s+0
        (?P<right>.*)$
    ''', re.VERBOSE)
    line_no = item.line_no
    error_text = editor.lines[line_no]
    for reg, fmt in ((zero_cmp, "{left}not {len}{right}"), (nzero_cmp, "{left}{len}{right}")):
        match = reg.match(error_text)
        if match:
            repaired_line = fmt.format(**match.groupdict())
            loc = (line_no, line_no + 1)
            editor.replace_range(loc, [repaired_line])


def  trailing_whitespace(editor, item):
    """ Pylint method to fix trailing-whitespace error """
    line_no = item.line_no
    repaired_line = editor.lines[line_no].rstrip()
    loc = (line_no, line_no + 1)
    editor.replace_range(loc, [repaired_line])


def ungrouped_imports(*_):
    """ Pylint ungrouped-imports method """
    pass


def anomalous_backslash_in_string(editor, item):
    """ Pylint anomalous-backslash-in-string method """
    line_no = item.line_no
    src = editor.lines[line_no]
    start, end = find_string(src)
    if (start, end) != (None, None):
        repaired_line = src[:start] + 'r' + src[start:]
        loc = (line_no, line_no + 1)
        editor.replace_range(loc, [repaired_line])
    else:
        LOGGER.info("Can't find anomalous string: '{0}'".format(src))


def no_op(*_):
    """ Pylint no-op method """
    pass


FN_TABLE = {
    "anomalous-backslash-in-string": anomalous_backslash_in_string,
    "bad-continuation": bad_continuation,
    "bad-whitespace": bad_whitespace,
    "invalid-name": invalid_name,
    "len-as-condition": len_as_condition,
    "misplaced-comparison-constant": misplaced_comparison_constant,
    "missing-docstring": missing_docstring,
    "no-self-use": no_self_use,
    "no-value-for-parameter": no_value_for_parameter,
    "superfluous-parens": superfluous_parens,
    "trailing-newline": trailing_newline,
    "trailing-whitespace": trailing_whitespace,
    "unused-import": unused_import,
    "ungrouped-imports": ungrouped_imports,
}

# pylint: disable=too-few-public-methods
# StreamEditor class has a minimal interface that a derived
# class must implement, so pylint is cranky about the number of
# methods implemented. Silence this warning.

# -----
class StreamEditorAutoPylint(StreamEditor):
    """
    Implement class for inserting debugging statements into a python file.
    (Reimplemented to use decorators on methods.)
    """
    table = [
        [[MODULE_NAME, NEXT], ],
        [[PYLINT_ITEM, REPEAT], [MODULE_NAME, CUT], ],
    ]

    def apply_match(self, _, dict_matches):
        """
        Implement the `apply_match` method to the file.
        """
        LOGGER.debug(dict_matches)
        matches = dict_matches["matches"]
        module, items = matches[0], [item_maker(m) for m in matches[1:] if "error" in m]

        filename = module["filename"].replace('.', '/') + ".py"
        keyfn = attrgetter('line_no')
        self.fix_pylint(filename, sorted(items, reverse=True, key=keyfn))

    @staticmethod
    def fix_pylint(filename, items):
        """ Fix all pylint errors that have a matching function """
        LOGGER.info("Creating StreamEditor for {0}".format(filename))

        affected = Counter()
        if not os.path.exists(filename):
            tmp_filename = os.path.join(filename[:-3], "__init__.py")
            if os.path.exists(tmp_filename):
                filename = tmp_filename

        try:
            editor = DerivedStreamEditor(filename, options=EditorOptions())
            for item in sorted(items, reverse=True, key=lambda x: x.line_no):
                LOGGER.info("Error at {1} is {0}".format(item.error, item.line_no))
                func = FN_TABLE.get(item.error, no_op)

                # Previous changes to the text may have shifted the line
                # number of the current error. Track these changes and apply
                # a patch when the problem is detected.
                distance = sum(v for k, v in affected.items() if k <= item.line_no)
                if distance:
                    item = Item(
                        item.type,
                        item.line_no + distance,
                        item.line_offset,
                        item.desc,
                        item.error
                    )

                line_no, count = func(editor, item)
                if count:
                    affected[line_no] += count
            editor.save()
        except IOError:
            LOGGER.exception("fix_pylint({0})".format(filename))


def main():
    """ Main entry point"""
    return call_main(StreamEditorAutoPylint)


if __name__ == '__main__':
    sys.exit(main())
