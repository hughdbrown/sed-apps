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
    REPEAT, NEXT, CUT, ANY,
)

MODULE_NAME = re.compile(r"""
    ^\*+\s
    Module\s+
    (?P<filename>[\w\d\._-]+)
    $
""", re.VERBOSE)

STD_IMPORT = re.compile(r"""
    ^
    standard\simport\s
    \"(?P<before>[^"]+)\"
    \sshould\sbe\splaced\sbefore\s
    \"(?P<after>[^"]+)\"
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
#C: 14, 0: Too many lines in module (6953/1000) (too-many-lines)
PYLINT_ITEM = re.compile(r"""
    ^
    (?P<type>[ERCW]):
    \s*
    (?P<where1>\d+),
    \s*
    (?P<where2>-?\d+):
    \s+
    (?P<desc>[\w\d\s\.\(\)/]+?)
    \s
    \(
    (?P<error>[\w_\.-]+?)
    \)
    $
""", re.VERBOSE)


# Some pylint errors do not have the error type until the second line after.
PYLINT_SEMI_ITEM = re.compile(r"""
    ^
    (?P<type>[ERCW]):
    \s*
    (?P<where1>\d+),
    \s*
    (?P<where2>-?\d+):
    \s+
    (?P<desc>[\w\d\s\.\(\)/]+?)
    $
""", re.VERBOSE)


PYLINT_ERROR_ITEM = re.compile(r"""
    ^
    [\^\s\|]+
    \(
    (?P<error>[\w_\.-]+)
    \)
    $
""", re.VERBOSE)

IF_STMT = re.compile(r"""
    ^
    if\s+
    (?P<first>.*?)
    \s+and\s+
    (?P<second>.*?):
    $
""", re.VERBOSE)


CONTINUATION = re.compile("""
    ^
    Wrong\scontinued\sindentation\s
    \(
    (?P<verb>.*?)
    \s(?P<count>\d+)\s+spaces
    \)
    \.
    $
""", re.VERBOSE)


HANGING = re.compile("""
    ^
    Wrong\shanging\sindentation\s
    (
        \(
        (?P<verb>.*?)
        \s(?P<count>\d+)\s+spaces
        \)
    )?
    \.
    $
""", re.VERBOSE)


# pylint: disable=logging-format-interpolation
logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


Item = namedtuple("Item", ["type", "line_no", "line_offset", "desc", "error"])
def item_maker(match):
    """ Helper function for making an Item from a dict """
    assert "type" in match
    assert "where1" in match
    assert "where2" in match
    assert "desc" in match
    assert "error" in match
    assert isinstance(match["desc"], str)
    assert isinstance(match["error"], str)
    return Item(
        match["type"],
        int(match["where1"]) - 1,
        int(match["where2"]),
        match["desc"].rstrip(),
        match["error"].rstrip()
    )


def get_indent(src):
    """ Helper function to get the leading whitespace from a line """
    match = re.match(r"^(\s*)(.*)$", src)
    return match.group(1), match.group(2)


def line_split(s, length):
    def get_counts(s, k):
        return [i for i, c in enumerate(s) if c == k]

    def remove_negative_counts(counts):
        try:
            return +counts
        except TypeError:
            return Counter({k: v for k, v in counts.items() if v > 0})

    if len(s) <= length:
        result = [s]
    else:
        ind0, non_indent = get_indent(s)
        ind1 = ind0 + "    "
        ind2 = ind0 + 2 * "    "
        m = IF_STMT.match(non_indent)
        if m:
            g = m.groupdict()
            result = [
                ind0 + "if (",
                ind2 + g["first"] + " and",
                ind2 + g["second"],
                ind0 + "):"
            ]
        else:
            counts = Counter({
                k: get_counts(s, k)
                for k in """()[]{}"'"""
            })
            counts = remove_negative_counts(counts)
            commas = get_counts(s, ',')

            cv = [a for a in counts.values() if a]
            if cv:
                mi, ma = min(a[0] for a in cv), max(a[-1] for a in cv)
                if (s[mi] + s[ma]) in {'()', '{}', '[]'}:
                    result = [s[:mi + 1], ind1 + s[mi + 1:ma], ind0 + s[ma:]]
                else:
                    result = None
            else:
                LOGGER.info("Weird: {0}".format(counts))
                result = None
    return result

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


def bad_whitespace(editor, item):
    """ Pylint method to fix bad-whitespace error """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    if item.desc == "No space allowed around keyword argument assignment":
        repaired_line = re.sub(r"\s+=\s+", "=", error_text, count=1)
    elif item.desc == "Exactly one space required after comma":
        repaired_line = re.sub(r",\s*", ", ", error_text)
    elif item.desc == "No space allowed after bracket":
        repaired_line = re.sub(r"{\s+", "{", error_text)
    elif item.desc == "No space allowed before bracket":
        repaired_line = re.sub(r"\s+}", "}", error_text)
    elif item.desc == "Exactly one space required around comparison":
        repaired_line = re.sub(r"\s*==\s*", " == ", error_text)
        repaired_line = re.sub(r"\s*!=\s*", " != ", repaired_line)
    else:
        LOGGER.info("No match on '{0}'".format(item.desc))
        repaired_line = None
    if repaired_line:
        LOGGER.info(repaired_line)
        editor.replace_range((line_no, line_no + 1), [repaired_line])
    return (line_no, 0)


def bad_continuation(editor, item):
    """ Pylint method to fix bad-continuation error """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    m = CONTINUATION.match(item.desc) or HANGING.match(item.desc)
    if m:
        g = m.groupdict()
        verb, count = g.get("verb"), int(g.get("count"))
        if verb and count < 16:
            repaired_line = (
                error_text[count:] if verb == "remove" else
                ((" " * count) + error_text if verb == "add"
                else None)
            )
            if repaired_line is not None:
                editor.replace_range((line_no, line_no + 1), [repaired_line])
    return (line_no, 0)


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
    return (line_no, loc[1] - loc[0])


def no_self_use(editor, item):
    """ Pylint method to fix no_self_use error """
    line_no = item.line_no
    LOGGER.info("no_self_use: {0}".format(line_no))
    error_text = editor.lines[line_no]
    LOGGER.info(error_text)
    indent, _ = get_indent(error_text)
    editor.lines[line_no] = error_text.replace("self, ", "").replace("(self)", "()")
    editor.insert_range(line_no, ["{0}@staticmethod".format(indent)])
    return (line_no, 1)


def no_value_for_parameter(editor, item):
    """ Pylint method to fix no_value_for_parameter error """
    line_no = item.line_no
    return (line_no, 0)


def superfluous_parens(editor, item):
    """ Pylint method to fix superfluous_parens error """
    line_no = item.line_no
    return (line_no, 0)


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
    return (line_no, 1)


def invalid_name(editor, item):
    """ Pylint method to fix invalid_name error """
    line_no = item.line_no
    return (line_no, 0)


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


def misplaced_comparison_constant(editor, item):
    """ Pylint method to fix misplaced_comparison_constant error """
    line_no = item.line_no
    return (line_no, 0)


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
    return (line_no, 0)


def trailing_whitespace(editor, item):
    """ Pylint method to fix trailing-whitespace error """
    line_no = item.line_no
    repaired_line = editor.lines[line_no].rstrip()
    loc = (line_no, line_no + 1)
    editor.replace_range(loc, [repaired_line])
    return (line_no, 0)


def ungrouped_imports(editor, item):
    """ Pylint ungrouped-imports method """
    line_no = item.line_no
    return (line_no, 0)


def unused_argument(editor, item):
    """ Pylint unused-argument method """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    LOGGER.info("unused argument: {0}".format(error_text))
    return (line_no, 0)


def unused_variable(editor, item):
    """ Pylint unused-variable method """
    unused_re = re.compile(r"Unused variable '(?P<unused>.*)'")
    line_no = item.line_no
    error_text = editor.lines[line_no]
    m = unused_re.search(item.desc)
    unused_var = r"\b{0[unused]}\b".format(m.groupdict())
    repaired_line = re.sub(unused_var, '_', error_text, count=1)
    loc = (line_no, line_no + 1)
    editor.replace_range(loc, [repaired_line])
    return (line_no, 0)


def wrong_import_order(editor, item):
    """ Pylint wrong_import_order method """
    line_no = item.line_no
    m = STD_IMPORT.match(item.desc)
    if m:
        g = m.groupdict()
        before, after = (
            re.compile("^{0}$".format(g[key]))
            for key in ("before", "after")
        )
        before_matches = list(editor.find_line(before))
        after_matches = list(editor.find_line(after))
        if len(before_matches) == 1 and len(after_matches) == 1:
            i, _ = before_matches[0]
            j, _ = after_matches[0]
            if i > j:
                # This case would not be true if a previous item
                # caused the order to be altered.
                line_nos = [i] + list(range(j + 1, i)) + [j]
                new_lines = [editor.lines[x] for x in line_nos]
                loc = (j, i + 1)
                assert len(new_lines) == (i + 1 - j)
                count_before = len(editor.lines)
                editor.replace_range(loc, new_lines)
                count_after = len(editor.lines)
                assert count_before == count_after
            else:
                LOGGER.info("Wrong import ordering already fixed")
    return (line_no, 0)


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
    return (line_no, 0)


def line_too_long(editor, item):
    line_no = item.line_no
    error_text = editor.lines[line_no]
    new_lines = line_split(error_text, 100)
    if not new_lines:
        LOGGER.info("Could not split: {0}".format(error_text))
        return (line_no, 0)
    else:
        assert isinstance(new_lines, list), new_lines
        assert all(isinstance(s, str) for s in new_lines)
        x = len(new_lines)
        editor.replace_range((line_no, line_no + 1), new_lines)
        return (line_no, x - 1)


def no_op(_, item):
    """ Pylint no-op method """
    line_no = item.line_no
    LOGGER.info("{0} goes to no-op".format(item.desc))
    return (line_no, 0)


def end_of_function_def(editor, start_line):
    for i in range(start_line, len(editor.lines)):
        if editor.lines[i].endswith("):"):
            return i
    return None


def end_of_string_doc(editor, start_line):
    for i in range(start_line, len(editor.lines)):
        if editor.lines[i].endswith(('"""', "'''")):
            return i
    return None


def dangerous_default_value(editor, item):
    """
    Pylint dangerous-default-value method
    GIVEN a line that has a mutable default argument
    THEN change the argument to None and add a line that converts a None argument
    to the required empty type.
    """
    line_no = item.line_no
    error_text = editor.lines[line_no]
    regex = r'Dangerous default value (?P<default_arg>.*?) as argument'
    m = re.match(regex, item.desc)
    if m:
        default_arg = m.groupdict()["default_arg"]
        regex = r'^.*(?P<arg_name>[\w\d_]+)(?P<spacing>\s*=\s*){0}.*$'.format(default_arg)
        m = re.match(regex, error_text)
        assert m, "No match on arg_name"

        # Set the variable correctly in the function scope
        # Skip to the end of the function def
        # Skip the string doc if present
        i = end_of_function_def(editor, line_no)
        if (i is not None) and editor.lines[i + 1].lstrip().startswith(('"""', "'''")):
            j = end_of_string_doc(editor, i + 1)
            i = i if j is None else j

        if m and (i is not None):
            g = m.groupdict()
            arg_name, spacing = tuple(g[arg] for arg in ("arg_name", "spacing"))

            # Fix the declaration in the function's argument list
            pattern = arg_name + spacing + default_arg
            repl = arg_name + "=None"
            new_decl = error_text.replace(pattern, repl)

            # Assign the default argument if the arg is None
            # HACK: should not assume that function is indented only 4 spaces
            spacing = "    "
            new_assign = "{0}{1} = {1} or {2}".format(spacing, arg_name, default_arg)

            # Perform multiple changes atomically
            editor.replace_range((line_no, line_no + 1), [new_decl])
            editor.append_range(i, [new_assign])
            return (i, 1)

    return (line_no, 0)


FN_TABLE = {
    "anomalous-backslash-in-string": anomalous_backslash_in_string,
    "bad-continuation": bad_continuation,
    "bad-whitespace": bad_whitespace,
    "invalid-name": invalid_name,
    "len-as-condition": len_as_condition,
    "line-too-long": line_too_long,
    "misplaced-comparison-constant": misplaced_comparison_constant,
    "missing-docstring": missing_docstring,
    "no-self-use": no_self_use,
    "no-value-for-parameter": no_value_for_parameter,
    "superfluous-parens": superfluous_parens,
    "trailing-newline": trailing_newline,
    "trailing-whitespace": trailing_whitespace,
    "ungrouped-imports": ungrouped_imports,
    "unused-argument": unused_argument,
    "unused-import": unused_import,
    "unused-variable": unused_variable,
    "wrong-import-order": wrong_import_order,
    "dangerous-default-value": dangerous_default_value,
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
        [[PYLINT_ITEM, REPEAT], [MODULE_NAME, CUT], [PYLINT_SEMI_ITEM, NEXT], ],
        [[ANY, NEXT], ],
        [[PYLINT_ERROR_ITEM, 1], [ANY, 1], ],
    ]

    def apply_match(self, _, dict_matches):
        """
        Implement the `apply_match` method to the file.
        """
        matches = dict_matches["matches"]

        # Because there can be complete matches and multiple lines which together
        # make up a match, we have to find them and glue them together. Also,
        # drop the fragments that have been glued on.
        deletes = set()
        lens = map(len, matches)
        LOGGER.info(lens)
        indexes = [i for i, l in enumerate(lens) if l == 5]
        for index in indexes:
            LOGGER.info(index)
            assert lens[index:index + 3] == [5, 1, 2], lens[index:index + 3]
            first, last = matches[index], matches[index + 2]
            assert 'error' in last, last
            assert 'error' not in first, first
            first['error'] = last['error']
            deletes.update([index + 1, index + 2])

        matches = [m for n, m in enumerate(matches) if n not in deletes]
        assert all(len(m) == 6 for m in matches[1:]), matches[1:]
        assert all("error" in m for m in matches[1:]), matches[1:]
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
