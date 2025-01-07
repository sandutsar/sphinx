from __future__ import annotations

import argparse
import fnmatch
import locale
import os
import os.path
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sphinx.locale
from sphinx import __display_version__
from sphinx.cmd.quickstart import EXTENSIONS
from sphinx.ext.apidoc import _remove_old_files, logger
from sphinx.ext.apidoc._generate import (
    CliOptions,
    create_modules_toc_file,
    recurse_tree,
)
from sphinx.locale import __
from sphinx.util.osutil import ensuredir

if TYPE_CHECKING:
    from collections.abc import Sequence


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        usage='%(prog)s [OPTIONS] -o <OUTPUT_PATH> <MODULE_PATH> [EXCLUDE_PATTERN, ...]',
        epilog=__('For more information, visit <https://www.sphinx-doc.org/>.'),
        description=__("""
Look recursively in <MODULE_PATH> for Python modules and packages and create
one reST file with automodule directives per package in the <OUTPUT_PATH>.

The <EXCLUDE_PATTERN>s can be file and/or directory patterns that will be
excluded from generation.

Note: By default this script will not overwrite already created files."""),
    )

    parser.add_argument(
        '--version',
        action='version',
        dest='show_version',
        version=f'%(prog)s {__display_version__}',
    )

    parser.add_argument('module_path', help=__('path to module to document'))
    parser.add_argument(
        'exclude_pattern',
        nargs='*',
        help=__(
            'fnmatch-style file and/or directory patterns to exclude from generation'
        ),
    )

    parser.add_argument(
        '-o',
        '--output-dir',
        action='store',
        dest='destdir',
        required=True,
        help=__('directory to place all output'),
    )
    parser.add_argument(
        '-q',
        action='store_true',
        dest='quiet',
        help=__('no output on stdout, just warnings on stderr'),
    )
    parser.add_argument(
        '-d',
        '--maxdepth',
        action='store',
        dest='maxdepth',
        type=int,
        default=4,
        help=__('maximum depth of submodules to show in the TOC (default: 4)'),
    )
    parser.add_argument(
        '-f',
        '--force',
        action='store_true',
        dest='force',
        help=__('overwrite existing files'),
    )
    parser.add_argument(
        '-l',
        '--follow-links',
        action='store_true',
        dest='followlinks',
        default=False,
        help=__(
            'follow symbolic links. Powerful when combined with collective.recipe.omelette.'
        ),
    )
    parser.add_argument(
        '-n',
        '--dry-run',
        action='store_true',
        dest='dryrun',
        help=__('run the script without creating files'),
    )
    parser.add_argument(
        '-e',
        '--separate',
        action='store_true',
        dest='separatemodules',
        help=__('put documentation for each module on its own page'),
    )
    parser.add_argument(
        '-P',
        '--private',
        action='store_true',
        dest='includeprivate',
        help=__('include "_private" modules'),
    )
    parser.add_argument(
        '--tocfile',
        action='store',
        dest='tocfile',
        default='modules',
        help=__('filename of table of contents (default: modules)'),
    )
    parser.add_argument(
        '-T',
        '--no-toc',
        action='store_false',
        dest='tocfile',
        help=__("don't create a table of contents file"),
    )
    parser.add_argument(
        '-E',
        '--no-headings',
        action='store_true',
        dest='noheadings',
        help=__(
            "don't create headings for the module/package "
            'packages (e.g. when the docstrings already '
            'contain them)'
        ),
    )
    parser.add_argument(
        '-M',
        '--module-first',
        action='store_true',
        dest='modulefirst',
        help=__('put module documentation before submodule documentation'),
    )
    parser.add_argument(
        '--implicit-namespaces',
        action='store_true',
        dest='implicit_namespaces',
        help=__(
            'interpret module paths according to PEP-0420 implicit namespaces specification'
        ),
    )
    parser.add_argument(
        '--automodule-options',
        dest='automodule_options',
        default='',
        help=__(
            'Comma-separated list of options to pass to automodule directive '
            '(or use SPHINX_APIDOC_OPTIONS).'
        ),
    )
    parser.add_argument(
        '-s',
        '--suffix',
        action='store',
        dest='suffix',
        default='rst',
        help=__('file suffix (default: rst)'),
    )
    exclusive_group = parser.add_mutually_exclusive_group()
    exclusive_group.add_argument(
        '--remove-old',
        action='store_true',
        dest='remove_old',
        help=__(
            'Remove existing files in the output directory that were not generated'
        ),
    )
    exclusive_group.add_argument(
        '-F',
        '--full',
        action='store_true',
        dest='full',
        help=__('generate a full project with sphinx-quickstart'),
    )
    parser.add_argument(
        '-a',
        '--append-syspath',
        action='store_true',
        dest='append_syspath',
        help=__('append module_path to sys.path, used when --full is given'),
    )
    parser.add_argument(
        '-H',
        '--doc-project',
        action='store',
        dest='header',
        help=__('project name (default: root module name)'),
    )
    parser.add_argument(
        '-A',
        '--doc-author',
        action='store',
        dest='author',
        help=__('project author(s), used when --full is given'),
    )
    parser.add_argument(
        '-V',
        '--doc-version',
        action='store',
        dest='version',
        help=__('project version, used when --full is given'),
    )
    parser.add_argument(
        '-R',
        '--doc-release',
        action='store',
        dest='release',
        help=__(
            'project release, used when --full is given, defaults to --doc-version'
        ),
    )

    group = parser.add_argument_group(__('extension options'))
    group.add_argument(
        '--extensions',
        metavar='EXTENSIONS',
        dest='extensions',
        action='append',
        help=__('enable arbitrary extensions, used when --full is given'),
    )
    for ext in EXTENSIONS:
        group.add_argument(
            f'--ext-{ext}',
            action='append_const',
            const=f'sphinx.ext.{ext}',
            dest='extensions',
            help=__('enable %s extension, used when --full is given') % ext,
        )

    group = parser.add_argument_group(__('Project templating'))
    group.add_argument(
        '-t',
        '--templatedir',
        metavar='TEMPLATEDIR',
        dest='templatedir',
        help=__('template directory for template files'),
    )

    return parser


def main(argv: Sequence[str] = (), /) -> int:
    """Run the apidoc CLI."""
    locale.setlocale(locale.LC_ALL, '')
    sphinx.locale.init_console()

    opts = _parse_args(argv)
    rootpath = opts.module_path
    excludes = tuple(
        re.compile(fnmatch.translate(os.path.abspath(exclude)))
        for exclude in dict.fromkeys(opts.exclude_pattern)
    )

    written_files, modules = recurse_tree(rootpath, excludes, opts, opts.templatedir)

    if opts.full:
        _full_quickstart(opts, modules=modules)
    elif opts.tocfile:
        written_files.append(
            create_modules_toc_file(modules, opts, opts.tocfile, opts.templatedir)
        )

    if opts.remove_old and not opts.dryrun:
        _remove_old_files(written_files, opts.destdir, opts.suffix)

    return 0


def _parse_args(argv: Sequence[str], /) -> CliOptions:
    parser = get_parser()
    args = parser.parse_args(argv or sys.argv[1:])

    # normalise options

    args.module_path = root_path = Path(args.module_path).resolve()
    args.destdir = Path(args.destdir)
    if not root_path.is_dir():
        logger.error(__('%s is not a directory.'), root_path)
        raise SystemExit(1)

    if args.header is None:
        args.header = root_path.name
    args.suffix = args.suffix.removeprefix('.')

    if not args.dryrun:
        ensuredir(args.destdir)

    if not args.automodule_options:
        args.automodule_options = set()
    elif isinstance(args.automodule_options, str):
        args.automodule_options = set(args.automodule_options.split(','))

    return CliOptions(**args.__dict__)


def _full_quickstart(opts: CliOptions, /, *, modules: list[str]) -> None:
    from sphinx.cmd import quickstart as qs

    modules.sort()
    prev_module = ''
    text = ''
    for module in modules:
        if module.startswith(prev_module + '.'):
            continue
        prev_module = module
        text += f'   {module}\n'
    d: dict[str, Any] = {
        'path': str(opts.destdir),
        'sep': False,
        'dot': '_',
        'project': opts.header,
        'author': opts.author or 'Author',
        'version': opts.version or '',
        'release': opts.release or opts.version or '',
        'suffix': '.' + opts.suffix,
        'master': 'index',
        'epub': True,
        'extensions': [
            'sphinx.ext.autodoc',
            'sphinx.ext.viewcode',
            'sphinx.ext.todo',
        ],
        'makefile': True,
        'batchfile': True,
        'make_mode': True,
        'mastertocmaxdepth': opts.maxdepth,
        'mastertoctree': text,
        'language': 'en',
        'module_path': str(opts.module_path),
        'append_syspath': opts.append_syspath,
    }
    if opts.extensions:
        d['extensions'].extend(opts.extensions)
    if opts.quiet:
        d['quiet'] = True

    for ext in d['extensions'][:]:
        if ',' in ext:
            d['extensions'].remove(ext)
            d['extensions'].extend(ext.split(','))

    if not opts.dryrun:
        qs.generate(d, silent=True, overwrite=opts.force, templatedir=opts.templatedir)