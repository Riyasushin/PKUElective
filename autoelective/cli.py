#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: cli.py
# modified: 2020-02-20

from optparse import OptionParser
from threading import Thread
from multiprocessing import Queue
from . import __version__, __date__


def create_default_parser():

    parser = OptionParser(
        description='PKU Auto-Elective Tool v%s (%s)' % (__version__, __date__),
        version=__version__,
    )

    ## custom input files

    parser.add_option(
        '-c',
        '--config',
        dest='config_ini',
        metavar="FILE",
        help='custom config file encoded with utf8',
    )

    ## boolean (flag) options
    parser.add_option('--check', action='store_true', default=False,
                      help='login and inspect one configured course without submitting')
    parser.add_option('--once', action='store_true', default=False,
                      help='attempt one configured course once, then verify and exit')
    parser.add_option('--captcha-attempts', type='int', default=3,
                      help='maximum captcha attempts in --once (default: 3)')

    parser.add_option(
        '-m',
        '--with-monitor',
        dest='with_monitor',
        action='store_true',
        default=False,
        help='run the monitor thread simultaneously',
    )

    return parser


def setup_default_environ(options, args, environ):

    environ.config_ini = options.config_ini
    environ.with_monitor = options.with_monitor


def create_default_threads(options, args, environ):

    # import here to ensure the singleton `config` will be init later than parse_args()
    from autoelective.loop import run_iaaa_loop, run_elective_loop
    from autoelective.monitor import run_monitor

    tList = []

    t = Thread(target=run_iaaa_loop, name="IAAA")
    environ.iaaa_loop_thread = t
    tList.append(t)

    t = Thread(target=run_elective_loop, name="Elective")
    environ.elective_loop_thread = t
    tList.append(t)

    if options.with_monitor:
        t = Thread(target=run_monitor, name="Monitor")
        environ.monitor_thread = t
        tList.append(t)

    return tList


def run():

    from .environ import Environ

    environ = Environ()

    parser = create_default_parser()
    options, args = parser.parse_args()

    setup_default_environ(options, args, environ)

    if options.check or options.once:
        if options.check and options.once:
            parser.error('--check and --once are mutually exclusive')
        if not 1 <= options.captcha_attempts <= 15:
            parser.error('--captcha-attempts must be between 1 and 15')
        from .config import AutoElectiveConfig
        from .workflow import run_once
        try:
            result = run_once(AutoElectiveConfig(), submit=options.once,
                              attempts=options.captcha_attempts)
            print('Result: %s' % result, flush=True)
        except Exception as exc:
            # Exception responses can contain credentials: print only the class.
            print('Failed: %s' % type(exc).__name__, flush=True)
            from .exceptions import RecognizerError
            if isinstance(exc, RecognizerError):
                print(str(exc), flush=True)  # Recognizer supplies a sanitized reason.
            raise SystemExit(1)
        if options.once and result not in ('elected', 'already_elected'):
            raise SystemExit(2)
        return

    tList = create_default_threads(options, args, environ)

    for t in tList:
        t.daemon = True
        t.start()

    #
    # Don't use join() to block the main thread, or Ctrl + C in Windows can't work.
    #
    # for t in tList:
    #     t.join()
    #
    try:
        Queue().get()
    except KeyboardInterrupt as e:
        pass
