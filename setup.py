#!/usr/bin/env python

from setuptools import setup, find_packages


def reqs_from_file(filename):
    with open(filename) as f:
        lineiter = (line.rstrip() for line in f if not line.startswith("#"))
        return list(filter(None, lineiter))


setup(
    name='sed-apps',
    version='0.1.2',
    description='Suite of tools that use sed-engine',
    author='Hugh Brown',
    author_email='hughdbrown@yahoo.com',

    # Required packages
    install_requires=reqs_from_file('requirements.txt'),
    tests_require=reqs_from_file('test-requirements.txt'),

    # Main packages
    #packages=[
    #    'src.javascript',
    #    'src.python',
    #],
    packages=find_packages(),
    zip_safe=False,

    entry_points={
        'console_scripts': [
            # Python modifiers
            'sed-python-func-debug=src.python.sed_python_func_debug:main',

            # Javascript modifiers
            'sed-at-this = src.javascript.sed_at_this:main',
            'sed-comment-merge = src.javascript.sed_comment_merge:main',
            'sed-docstrings = src.javascript.sed_docstrings:main',
            'sed-events = src.javascript.sed_events:main',
            'sed-extend-decl = src.javascript.sed_extend_decl:main',
            'sed-inject-delegate-events = src.javascript.sed_inject_delegate_events:main',
            'sed-inject-private = src.javascript.sed_inject_private:main',
            'sed-move-events = src.javascript.sed_move_events:main',
            'sed-quote-members = src.javascript.sed_quote_members:main',
            'sed-require-sort = src.javascript.sed_require_sort:main',
            'sed-revert-delegate-events = src.javascript.sed_revert_delegate_events:main',
            'sed-rewrite-app-get = src.javascript.sed_rewrite_app_get:main',
        ],
    },
)
