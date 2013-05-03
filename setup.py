#!/usr/bin/env python

from setuptools import setup


def reqs_from_file(filename):
    with open(filename) as f:
        lineiter = (line.rstrip() for line in f if not line.startswith("#"))
        return list(filter(None, lineiter))


setup(
    name='sed-apps',
    version='0.1.1',
    description='Suite of tools that use sed-engine',
    author='Hugh Brown',
    author_email='hughdbrown@yahoo.com',

    # Required packages
    install_requires=reqs_from_file('requirements.txt'),
    tests_require=reqs_from_file('test-requirements.txt'),

    # Main packages
    packages=[
        'src',
    ],

    zip_safe=False,

    scripts=[
        'bin/sed-at-this',
        'bin/sed-comment-merge',
        'bin/sed-docstrings',
        'bin/sed-events',
        'bin/sed-extend-decl',
        'bin/sed-inject-delegate-events',
        'bin/sed-inject-private',
        'bin/sed-move-events',
        'bin/sed-quote-members',
        'bin/sed-require-sort',
        'bin/sed-revert-delegate-events',
        'bin/sed-rewrite-app-get',
    ],
    entry_points={
        'console_scripts': [
            'sed-at-this = src.sed_at_this:main',
            'sed-comment-merge = src.sed_comment_merge:main',
            'sed-docstrings = src.sed_docstrings:main',
            'sed-events = src.sed_events:main',
            'sed-extend-decl = src.sed_extend_decl:main',
            'sed-inject-delegate-events = src.sed_inject_delegate_events:main',
            'sed-inject-private = src.sed_inject_private:main',
            'sed-move-events = src.sed_move_events:main',
            'sed-quote-members = src.sed_quote_members:main',
            'sed-require-sort = src.sed_require_sort:main',
            'sed-revert-delegate-events = src.sed_revert_delegate_events:main',
            'sed-rewrite-app-get = src.sed_rewrite_app_get:main',
        ],
    },
)
