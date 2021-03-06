# worker.py - master-slave parallelism support
#
# Copyright 2013 Facebook, Inc.
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import absolute_import

import errno
import os
import signal
import sys
import threading
import time

from .i18n import _
from . import (
    encoding,
    error,
    pycompat,
    scmutil,
    util,
)

def countcpus():
    '''try to count the number of CPUs on the system'''

    # posix
    try:
        n = int(os.sysconf(r'SC_NPROCESSORS_ONLN'))
        if n > 0:
            return n
    except (AttributeError, ValueError):
        pass

    # windows
    try:
        n = int(encoding.environ['NUMBER_OF_PROCESSORS'])
        if n > 0:
            return n
    except (KeyError, ValueError):
        pass

    return 1

def _numworkers(ui):
    s = ui.config('worker', 'numcpus')
    if s:
        try:
            n = int(s)
            if n >= 1:
                return n
        except ValueError:
            raise error.Abort(_('number of cpus must be an integer'))
    return min(max(countcpus(), 4), 32)

if pycompat.isposix or pycompat.iswindows:
    _startupcost = 0.01
else:
    _startupcost = 1e30

def worthwhile(ui, costperop, nops):
    '''try to determine whether the benefit of multiple processes can
    outweigh the cost of starting them'''
    linear = costperop * nops
    workers = _numworkers(ui)
    benefit = linear - (_startupcost * workers + linear / workers)
    return benefit >= 0.15

def worker(ui, costperarg, func, staticargs, args):
    '''run a function, possibly in parallel in multiple worker
    processes.

    returns a progress iterator

    costperarg - cost of a single task

    func - function to run

    staticargs - arguments to pass to every invocation of the function

    args - arguments to split into chunks, to pass to individual
    workers
    '''
    enabled = ui.configbool('worker', 'enabled')
    if enabled and worthwhile(ui, costperarg, len(args)):
        return _platformworker(ui, func, staticargs, args)
    return func(*staticargs + (args,))

def _posixworker(ui, func, staticargs, args):
    rfd, wfd = os.pipe()
    workers = _numworkers(ui)
    oldhandler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    pids, problem = set(), [0]
    def killworkers():
        # unregister SIGCHLD handler as all children will be killed. This
        # function shouldn't be interrupted by another SIGCHLD; otherwise pids
        # could be updated while iterating, which would cause inconsistency.
        signal.signal(signal.SIGCHLD, oldchldhandler)
        # if one worker bails, there's no good reason to wait for the rest
        for p in pids:
            try:
                os.kill(p, signal.SIGTERM)
            except OSError as err:
                if err.errno != errno.ESRCH:
                    raise
    def waitforworkers(blocking=True):
        for pid in pids.copy():
            p = st = 0
            while True:
                try:
                    p, st = os.waitpid(pid, (0 if blocking else os.WNOHANG))
                    break
                except OSError as e:
                    if e.errno == errno.EINTR:
                        continue
                    elif e.errno == errno.ECHILD:
                        # child would already be reaped, but pids yet been
                        # updated (maybe interrupted just after waitpid)
                        pids.discard(pid)
                        break
                    else:
                        raise
            if not p:
                # skip subsequent steps, because child process should
                # be still running in this case
                continue
            pids.discard(p)
            st = _exitstatus(st)
            if st and not problem[0]:
                problem[0] = st
    def sigchldhandler(signum, frame):
        waitforworkers(blocking=False)
        if problem[0]:
            killworkers()
    oldchldhandler = signal.signal(signal.SIGCHLD, sigchldhandler)
    ui.flush()
    parentpid = os.getpid()
    for pargs in partition(args, workers):
        # make sure we use os._exit in all worker code paths. otherwise the
        # worker may do some clean-ups which could cause surprises like
        # deadlock. see sshpeer.cleanup for example.
        # override error handling *before* fork. this is necessary because
        # exception (signal) may arrive after fork, before "pid =" assignment
        # completes, and other exception handler (dispatch.py) can lead to
        # unexpected code path without os._exit.
        ret = -1
        try:
            pid = os.fork()
            if pid == 0:
                signal.signal(signal.SIGINT, oldhandler)
                signal.signal(signal.SIGCHLD, oldchldhandler)

                def workerfunc():
                    os.close(rfd)
                    for i, item in func(*(staticargs + (pargs,))):
                        os.write(wfd, '%d %s\n' % (i, item))
                    return 0

                ret = scmutil.callcatch(ui, workerfunc)
        except: # parent re-raises, child never returns
            if os.getpid() == parentpid:
                raise
            exctype = sys.exc_info()[0]
            force = not issubclass(exctype, KeyboardInterrupt)
            ui.traceback(force=force)
        finally:
            if os.getpid() != parentpid:
                try:
                    ui.flush()
                except: # never returns, no re-raises
                    pass
                finally:
                    os._exit(ret & 255)
        pids.add(pid)
    os.close(wfd)
    fp = os.fdopen(rfd, r'rb', 0)
    def cleanup():
        signal.signal(signal.SIGINT, oldhandler)
        waitforworkers()
        signal.signal(signal.SIGCHLD, oldchldhandler)
        status = problem[0]
        if status:
            if status < 0:
                os.kill(os.getpid(), -status)
            sys.exit(status)
    try:
        for line in util.iterfile(fp):
            l = line.split(' ', 1)
            yield int(l[0]), l[1][:-1]
    except: # re-raises
        killworkers()
        cleanup()
        raise
    cleanup()

def _posixexitstatus(code):
    '''convert a posix exit status into the same form returned by
    os.spawnv

    returns None if the process was stopped instead of exiting'''
    if os.WIFEXITED(code):
        return os.WEXITSTATUS(code)
    elif os.WIFSIGNALED(code):
        return -os.WTERMSIG(code)

def _windowsworker(ui, func, staticargs, args):
    class Worker(threading.Thread):
        def __init__(self, taskqueue, resultqueue, func, staticargs,
                     group=None, target=None, name=None, verbose=None):
            threading.Thread.__init__(self, group=group, target=target,
                                      name=name, verbose=verbose)
            self._taskqueue = taskqueue
            self._resultqueue = resultqueue
            self._func = func
            self._staticargs = staticargs
            self._interrupted = False
            self.daemon = True
            self.exception = None

        def interrupt(self):
            self._interrupted = True

        def run(self):
            try:
                while not self._taskqueue.empty():
                    try:
                        args = self._taskqueue.get_nowait()
                        for res in self._func(*self._staticargs + (args,)):
                            self._resultqueue.put(res)
                            # threading doesn't provide a native way to
                            # interrupt execution. handle it manually at every
                            # iteration.
                            if self._interrupted:
                                return
                    except util.empty:
                        break
            except Exception as e:
                # store the exception such that the main thread can resurface
                # it as if the func was running without workers.
                self.exception = e
                raise

    threads = []
    def trykillworkers():
        # Allow up to 1 second to clean worker threads nicely
        cleanupend = time.time() + 1
        for t in threads:
            t.interrupt()
        for t in threads:
            remainingtime = cleanupend - time.time()
            t.join(remainingtime)
            if t.is_alive():
                # pass over the workers joining failure. it is more
                # important to surface the inital exception than the
                # fact that one of workers may be processing a large
                # task and does not get to handle the interruption.
                ui.warn(_("failed to kill worker threads while "
                          "handling an exception\n"))
                return

    workers = _numworkers(ui)
    resultqueue = util.queue()
    taskqueue = util.queue()
    # partition work to more pieces than workers to minimize the chance
    # of uneven distribution of large tasks between the workers
    for pargs in partition(args, workers * 20):
        taskqueue.put(pargs)
    for _i in range(workers):
        t = Worker(taskqueue, resultqueue, func, staticargs)
        threads.append(t)
        t.start()
    try:
        while len(threads) > 0:
            while not resultqueue.empty():
                yield resultqueue.get()
            threads[0].join(0.05)
            finishedthreads = [_t for _t in threads if not _t.is_alive()]
            for t in finishedthreads:
                if t.exception is not None:
                    raise t.exception
                threads.remove(t)
    except (Exception, KeyboardInterrupt): # re-raises
        trykillworkers()
        raise
    while not resultqueue.empty():
        yield resultqueue.get()

if pycompat.iswindows:
    _platformworker = _windowsworker
else:
    _platformworker = _posixworker
    _exitstatus = _posixexitstatus

def partition(lst, nslices):
    '''partition a list into N slices of roughly equal size

    The current strategy takes every Nth element from the input. If
    we ever write workers that need to preserve grouping in input
    we should consider allowing callers to specify a partition strategy.

    mpm is not a fan of this partitioning strategy when files are involved.
    In his words:

        Single-threaded Mercurial makes a point of creating and visiting
        files in a fixed order (alphabetical). When creating files in order,
        a typical filesystem is likely to allocate them on nearby regions on
        disk. Thus, when revisiting in the same order, locality is maximized
        and various forms of OS and disk-level caching and read-ahead get a
        chance to work.

        This effect can be quite significant on spinning disks. I discovered it
        circa Mercurial v0.4 when revlogs were named by hashes of filenames.
        Tarring a repo and copying it to another disk effectively randomized
        the revlog ordering on disk by sorting the revlogs by hash and suddenly
        performance of my kernel checkout benchmark dropped by ~10x because the
        "working set" of sectors visited no longer fit in the drive's cache and
        the workload switched from streaming to random I/O.

        What we should really be doing is have workers read filenames from a
        ordered queue. This preserves locality and also keeps any worker from
        getting more than one file out of balance.
    '''
    for i in range(nslices):
        yield lst[i::nslices]
