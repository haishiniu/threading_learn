# -*- coding: utf-8 -*-
# !/usr/bin/python
"""Thread module emulating a subset of Java's threading model."""

import sys as _sys

try:
    import thread
except ImportError:
    del _sys.modules[__name__]
    raise

import warnings

from collections import deque as _deque
from itertools import count as _count
from time import time as _time, sleep as _sleep
from traceback import format_exc as _format_exc

# Note regarding PEP 8 compliant aliases
#  This threading model was originally inspired by Java, and inherited
# the convention of camelCase function and method names from that
# language. While those names are not in any imminent danger of being
# deprecated, starting with Python 2.6, the module now provides a
# PEP 8 compliant alias for any such method name.
# Using the new PEP 8 compliant names also facilitates substitution
# with the multiprocessing module, which doesn't provide the old
# Java inspired names.


# Rename some stuff so "from threading import *" is safe
__all__ = ['activeCount', 'active_count', 'Condition', 'currentThread',
           'current_thread', 'enumerate', 'Event',
           'Lock', 'RLock', 'Semaphore', 'BoundedSemaphore', 'Thread',
           'Timer', 'setprofile', 'settrace', 'local', 'stack_size']

_start_new_thread = thread.start_new_thread
_allocate_lock = thread.allocate_lock
# 返回唯一标识当前线程的非零整数
#      以及同时存在的其他线程。
#      这可以用来识别每个线程资源。
#      即使在某些平台上线程身份可能看起来像
#      从1开始分配连续的数字，这种行为不应该
#      这个数字应该被看作纯粹的魔法饼干。
#      一个线程的身份可以在退出后重新用于另一个线程。
_get_ident = thread.get_ident
ThreadError = thread.error
del thread


# sys.exc_clear is used to work around the fact that except blocks
# don't fully clear the exception until 3.0.
warnings.filterwarnings('ignore', category=DeprecationWarning,
                        module='threading', message='sys.exc_clear')

# Debug support (adapted from ihooks.py).
# All the major classes here derive from _Verbose.  We force that to
# be a new-style class so that all the major classes here are new-style.
# This helps debugging (type(instance) is more revealing for instances
# of new-style classes).

_VERBOSE = False

if __debug__:

    class _Verbose(object):
        def __init__(self, verbose=None):
            if verbose is None:
                verbose = _VERBOSE
            self.__verbose = verbose

        def _note(self, format, *args):
            if self.__verbose:
                format = format % args
                # Issue #4188: calling current_thread() can incur an infinite
                # recursion if it has to create a DummyThread on the fly.
                ident = _get_ident()
                try:
                    name = _active[ident].name
                except KeyError:
                    name = "<OS thread %d>" % ident
                format = "%s: %s\n" % (name, format)
                print ('22223%s' % format)
                _sys.stderr.write(format)

else:
    # Disable this when using "python -O"
    class _Verbose(object):
        def __init__(self, verbose=None):
            pass
        def _note(self, *args):
            pass

# Support for profile and trace hooks

_profile_hook = None
_trace_hook = None

def setprofile(func):
    """Set a profile function for all threads started from the threading module.

    The func will be passed to sys.setprofile() for each thread, before its
    run() method is called.

    """
    global _profile_hook
    _profile_hook = func

def settrace(func):
    """Set a trace function for all threads started from the threading module.

    The func will be passed to sys.settrace() for each thread, before its run()
    method is called.

    """
    global _trace_hook
    _trace_hook = func

# Synchronization classes

Lock = _allocate_lock

def RLock(*args, **kwargs):
    """Factory function that returns a new reentrant lock.

    A reentrant lock must be released by the thread that acquired it. Once a
    thread has acquired a reentrant lock, the same thread may acquire it again
    without blocking; the thread must release it once for each time it has
    acquired it.

    """
    return _RLock(*args, **kwargs)

class _RLock(_Verbose):
    """A reentrant lock must be released by the thread that acquired it. Once a
       thread has acquired a reentrant lock, the same thread may acquire it
       again without blocking; the thread must release it once for each time it
       has acquired it.
    """

    def __init__(self, verbose=None):
        _Verbose.__init__(self, verbose)
        self.__block = _allocate_lock()
        self.__owner = None
        self.__count = 0

    def __repr__(self):
        owner = self.__owner
        try:
            owner = _active[owner].name
        except KeyError:
            pass
        return "<%s owner=%r count=%d>" % (
                self.__class__.__name__, owner, self.__count)

    def acquire(self, blocking=1):
        """Acquire a lock, blocking or non-blocking.

        When invoked without arguments: if this thread already owns the lock,
        increment the recursion level by one, and return immediately. Otherwise,
        if another thread owns the lock, block until the lock is unlocked. Once
        the lock is unlocked (not owned by any thread), then grab ownership, set
        the recursion level to one, and return. If more than one thread is
        blocked waiting until the lock is unlocked, only one at a time will be
        able to grab ownership of the lock. There is no return value in this
        case.

        When invoked with the blocking argument set to true, do the same thing
        as when called without arguments, and return true.

        When invoked with the blocking argument set to false, do not block. If a
        call without an argument would block, return false immediately;
        otherwise, do the same thing as when called without arguments, and
        return true.

        """
        me = _get_ident()
        if self.__owner == me:
            self.__count = self.__count + 1
            if __debug__:
                self._note("%s.acquire(%s): recursive success", self, blocking)
            return 1
        rc = self.__block.acquire(blocking)  # 自己调用自己，形成递归操作
        if rc:
            self.__owner = me
            self.__count = 1
            if __debug__:
                self._note("%s.acquire(%s): initial success", self, blocking)
        else:
            if __debug__:
                self._note("%s.acquire(%s): failure", self, blocking)
        return rc

    __enter__ = acquire

    def release(self):
        """Release a lock, decrementing the recursion level.

        If after the decrement it is zero, reset the lock to unlocked (not owned
        by any thread), and if any other threads are blocked waiting for the
        lock to become unlocked, allow exactly one of them to proceed. If after
        the decrement the recursion level is still nonzero, the lock remains
        locked and owned by the calling thread.

        Only call this method when the calling thread owns the lock. A
        RuntimeError is raised if this method is called when the lock is
        unlocked.

        There is no return value.

        """
        # 释放一个锁，递减递归级别。
        #
        #          如果在递减之后它为零，则重置锁以解锁（不属于
        #          由任何线程），以及是否有其他线程阻塞等待
        #          锁定变为解锁状态，准确地让其中的一个继续。 如果之后
        #          递归级别递减仍然不为零，锁仍然存在
        #          锁定并由调用线程拥有。
        #          只有在调用线程拥有锁定时才调用此方法。 一个
        #          如果在锁定时调用此方法，则会引发RuntimeError
        #         解锁。
        #          没有返回值。
        if self.__owner != _get_ident():
            raise RuntimeError("cannot release un-acquired lock")
        self.__count = count = self.__count - 1
        if not count:
            self.__owner = None
            self.__block.release()
            if __debug__:
                self._note("%s.release(): final release", self)
        else:
            if __debug__:
                self._note("%s.release(): non-final release", self)

    def __exit__(self, t, v, tb):
        self.release()

    # Internal methods used by condition variables

    def _acquire_restore(self, count_owner):
        count, owner = count_owner
        self.__block.acquire()
        self.__count = count
        self.__owner = owner
        if __debug__:
            self._note("%s._acquire_restore()", self)

    def _release_save(self):  # 释放
        if __debug__:
            self._note("%s._release_save()", self)
        count = self.__count  # 拿出现在的线程的计数器
        self.__count = 0  # 把对象的计数器设置为0
        owner = self.__owner  # 取出这个id号码
        self.__owner = None  # 设置为Node
        self.__block.release()  #
        return (count, owner)

    def _is_owned(self):
        return self.__owner == _get_ident()


def Condition(*args, **kwargs):
    """Factory function that returns a new condition variable object.

    A condition variable allows one or more threads to wait until they are
    notified by another thread.

    If the lock argument is given and not None, it must be a Lock or RLock
    object, and it is used as the underlying lock. Otherwise, a new RLock object
    is created and used as the underlying lock.

    """
    return _Condition(*args, **kwargs)

class _Condition(_Verbose):
    """Condition variables allow one or more threads to wait until they are
       notified by another thread.
    """

    def __init__(self, lock=None, verbose=None):
        _Verbose.__init__(self, verbose)
        if lock is None:
            lock = RLock()
        self.__lock = lock
        # Export the lock's acquire() and release() methods  导出锁的acquire（）和release（）方法
        self.acquire = lock.acquire
        self.release = lock.release
        # If the lock defines _release_save() and/or _acquire_restore(),
        # these override the default implementations (which just call
        # release() and acquire() on the lock).  Ditto for _is_owned().

        # 如果锁定器定义了_release_save（）和/或_acquire_restore（），它们会[覆盖]默认实现（它们只是在锁上调用release（）
        # 和acquire（））。 同上_is_owned（）。
        try:
            self._release_save = lock._release_save
        except AttributeError:
            pass
        try:
            self._acquire_restore = lock._acquire_restore
        except AttributeError:
            pass
        try:
            self._is_owned = lock._is_owned
        except AttributeError:
            pass
        self.__waiters = []

    def __enter__(self):
        return self.__lock.__enter__()

    def __exit__(self, *args):
        return self.__lock.__exit__(*args)

    def __repr__(self):
        return "<Condition(%s, %d)>" % (self.__lock, len(self.__waiters))

    def _release_save(self):
        self.__lock.release()           # No state to save

    def _acquire_restore(self, x):
        self.__lock.acquire()           # Ignore saved state

    def _is_owned(self):
        # Return True if lock is owned by current_thread.
        # This method is called only if __lock doesn't have _is_owned().
        # 如果lock属于current_thread，则返回True。仅当__lock没有_is_owned（）时才调用此方法
        if self.__lock.acquire(0):
            self.__lock.release()
            return False
        else:
            return True

    def wait(self, timeout=None):
        """Wait until notified or until a timeout occurs.

        If the calling thread has not acquired the lock when this method is
        called, a RuntimeError is raised.

        This method releases the underlying lock, and then blocks until it is
        awakened by a notify() or notifyAll() call for the same condition
        variable in another thread, or until the optional timeout occurs. Once
        awakened or timed out, it re-acquires the lock and returns.

        When the timeout argument is present and not None, it should be a
        floating point number specifying a timeout for the operation in seconds
        (or fractions thereof).

        When the underlying lock is an RLock, it is not released using its
        release() method, since this may not actually unlock the lock when it
        was acquired multiple times recursively. Instead, an internal interface
        of the RLock class is used, which really unlocks it even when it has
        been recursively acquired several times. Another internal interface is
        then used to restore the recursion level when the lock is reacquired.

        """
        # 等到通知或直到发生超时。
        #
        #         如果调用线程在此方法时没有获得锁定
        #         称为，引发了一个RuntimeError。
        #
        #         此方法释放【底层锁】，然后阻塞直到它
        #         通过notify（）或notifyAll（）调用唤醒相同的条件
        #         在另一个线程中变量，或直到发生可选的超时。一旦
        #         唤醒或超时，它重新获得锁定并返回。
        #
        #         当超时参数存在而不是无时，它应该是a
        #         浮点数指定操作的超时值，以秒为单位
        #         （或其部分）。
        #
        #         当底层锁定是RLock时，它不会使用其释放
        #         release（）方法，因为这可能实际上并不解锁锁
        #         被递归获取多次。而是一个内部接口
        #         的RLock类被使用，即使它已经真正解锁了它
        #         已被递归获得数次。另一个内部接口是
        #         然后用于在重新获取锁定时恢复递归级别。

        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
        waiter = _allocate_lock()
        waiter.acquire()
        self.__waiters.append(waiter)
        saved_state = self._release_save()  # 保存状态  # 释放保存  # (count, owner)返回计数器和线程信息
        try:    # restore state no matter what (e.g., KeyboardInterrupt)
            if timeout is None:
                waiter.acquire()
                if __debug__:
                    self._note("%s.wait(): got it", self)
            else:
                # Balancing act:  We can't afford a pure busy loop, so we
                # have to sleep; but if we sleep the whole timeout time,
                # we'll be unresponsive.  The scheme here sleeps very
                # little at first, longer as time goes on, but never longer
                # than 20 times per second (or the timeout time remaining).
                endtime = _time() + timeout
                delay = 0.0005 # 500 us -> initial delay of 1 ms
                while True:
                    gotit = waiter.acquire(0)
                    if gotit:
                        break
                    remaining = endtime - _time()
                    if remaining <= 0:
                        break
                    delay = min(delay * 2, remaining, .05)
                    _sleep(delay)
                if not gotit:
                    if __debug__:
                        self._note("%s.wait(%s): timed out", self, timeout)
                    try:
                        self.__waiters.remove(waiter)
                    except ValueError:
                        pass
                else:
                    if __debug__:
                        self._note("%s.wait(%s): got it", self, timeout)
        finally:
            self._acquire_restore(saved_state)

    def notify(self, n=1):
        """Wake up one or more threads waiting on this condition, if any.

        If the calling thread has not acquired the lock when this method is
        called, a RuntimeError is raised.

        This method wakes up at most n of the threads waiting for the condition
        variable; it is a no-op if no threads are waiting.

        """
        # 唤醒一个或多个等待这种情况的线程（如果有的话）。 如果在调用此方法时调用线程未获取锁，
        # 则会引发RuntimeError。此方法至多会唤醒等待条件变量的n个线程;
        # 如果没有线程正在等待，则它是无操作的。
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        __waiters = self.__waiters  # 等待池中的线程
        waiters = __waiters[:n]  # 获取等待着（前n个等待着）线程
        if not waiters:  # 执行start()方法是不会有等待线程，会直接返回
            if __debug__:
                self._note("%s.notify(): no waiters", self)
            return
        self._note("%s.notify(): notifying %d waiter%s", self, n,
                   n!=1 and "s" or "")
        for waiter in waiters:
            waiter.release()
            try:
                __waiters.remove(waiter)
            except ValueError:
                pass

    def notifyAll(self):
        """Wake up all threads waiting on this condition.

        If the calling thread has not acquired the lock when this method
        is called, a RuntimeError is raised.

        """
        # 唤醒等待这种情况的所有线程。
        #          如果调用线程在此方法未获取锁时
        #          被调用时，会引发RuntimeError。
        self.notify(len(self.__waiters))

    notify_all = notifyAll


def Semaphore(*args, **kwargs):
    """A factory function that returns a new semaphore.

    Semaphores manage a counter representing the number of release() calls minus
    the number of acquire() calls, plus an initial value. The acquire() method
    blocks if necessary until it can return without making the counter
    negative. If not given, value defaults to 1.

    """
    return _Semaphore(*args, **kwargs)

class _Semaphore(_Verbose):
    """Semaphores manage a counter representing the number of release() calls
       minus the number of acquire() calls, plus an initial value. The acquire()
       method blocks if necessary until it can return without making the counter
       negative. If not given, value defaults to 1.

    """

    # After Tim Peters' semaphore class, but not quite the same (no maximum)

    def __init__(self, value=1, verbose=None):
        if value < 0:
            raise ValueError("semaphore initial value must be >= 0")
        _Verbose.__init__(self, verbose)
        self.__cond = Condition(Lock())
        self.__value = value

    def acquire(self, blocking=1):
        """Acquire a semaphore, decrementing the internal counter by one.

        When invoked without arguments: if the internal counter is larger than
        zero on entry, decrement it by one and return immediately. If it is zero
        on entry, block, waiting until some other thread has called release() to
        make it larger than zero. This is done with proper interlocking so that
        if multiple acquire() calls are blocked, release() will wake exactly one
        of them up. The implementation may pick one at random, so the order in
        which blocked threads are awakened should not be relied on. There is no
        return value in this case.

        When invoked with blocking set to true, do the same thing as when called
        without arguments, and return true.

        When invoked with blocking set to false, do not block. If a call without
        an argument would block, return false immediately; otherwise, do the
        same thing as when called without arguments, and return true.

        """
        rc = False
        with self.__cond:
            while self.__value == 0:
                if not blocking:
                    break
                if __debug__:
                    self._note("%s.acquire(%s): blocked waiting, value=%s",
                            self, blocking, self.__value)
                self.__cond.wait()
            else:
                self.__value = self.__value - 1
                if __debug__:
                    self._note("%s.acquire: success, value=%s",
                            self, self.__value)
                rc = True
        return rc

    __enter__ = acquire

    def release(self):
        """Release a semaphore, incrementing the internal counter by one.

        When the counter is zero on entry and another thread is waiting for it
        to become larger than zero again, wake up that thread.

        """
        with self.__cond:
            self.__value = self.__value + 1
            if __debug__:
                self._note("%s.release: success, value=%s",
                        self, self.__value)
            self.__cond.notify()

    def __exit__(self, t, v, tb):
        self.release()


def BoundedSemaphore(*args, **kwargs):
    """A factory function that returns a new bounded semaphore.

    A bounded semaphore checks to make sure its current value doesn't exceed its
    initial value. If it does, ValueError is raised. In most situations
    semaphores are used to guard resources with limited capacity.

    If the semaphore is released too many times it's a sign of a bug. If not
    given, value defaults to 1.

    Like regular semaphores, bounded semaphores manage a counter representing
    the number of release() calls minus the number of acquire() calls, plus an
    initial value. The acquire() method blocks if necessary until it can return
    without making the counter negative. If not given, value defaults to 1.

    """
    return _BoundedSemaphore(*args, **kwargs)

class _BoundedSemaphore(_Semaphore):
    """A bounded semaphore checks to make sure its current value doesn't exceed
       its initial value. If it does, ValueError is raised. In most situations
       semaphores are used to guard resources with limited capacity.
    """

    def __init__(self, value=1, verbose=None):
        _Semaphore.__init__(self, value, verbose)
        self._initial_value = value

    def release(self):
        """Release a semaphore, incrementing the internal counter by one.

        When the counter is zero on entry and another thread is waiting for it
        to become larger than zero again, wake up that thread.

        If the number of releases exceeds the number of acquires,
        raise a ValueError.

        """
        with self._Semaphore__cond:
            if self._Semaphore__value >= self._initial_value:
                raise ValueError("Semaphore released too many times")
            self._Semaphore__value += 1
            self._Semaphore__cond.notify()


def Event(*args, **kwargs):
    """A factory function that returns a new event.

    Events manage a flag that can be set to true with the set() method and reset
    to false with the clear() method. The wait() method blocks until the flag is
    true.

    """
    return _Event(*args, **kwargs)

class _Event(_Verbose):
    """A factory function that returns a new event object. An event manages a
       flag that can be set to true with the set() method and reset to false
       with the clear() method. The wait() method blocks until the flag is true.

    """

    # After Tim Peters' event class (without is_posted())

    def __init__(self, verbose=None):
        _Verbose.__init__(self, verbose)
        self.__cond = Condition(Lock())
        self.__flag = False

    def _reset_internal_locks(self):
        # private!  called by Thread._reset_internal_locks by _after_fork()
        self.__cond.__init__()

    def isSet(self):
        'Return true if and only if the internal flag is true.'
        # 当且仅当内部标志为真时返回true
        return self.__flag

    is_set = isSet

    def set(self):
        """Set the internal flag to true.

        All threads waiting for the flag to become true are awakened. Threads
        that call wait() once the flag is true will not block at all.

        """
        # 将内部标志设置为true。
        # 等待标志变为真的所有线程都被唤醒。主题
        # 那个调用wait（）一旦标志为真就根本不会阻塞。
        self.__cond.acquire()
        try:
            self.__flag = True
            self.__cond.notify_all()  # 唤醒所有的线程 执行start（）方法
        finally:
            self.__cond.release()

    def clear(self):
        """Reset the internal flag to false.

        Subsequently, threads calling wait() will block until set() is called to
        set the internal flag to true again.

        """
        self.__cond.acquire()
        try:
            self.__flag = False
        finally:
            self.__cond.release()

    def wait(self, timeout=None):
        """Block until the internal flag is true.

        If the internal flag is true on entry, return immediately. Otherwise,
        block until another thread calls set() to set the flag to true, or until
        the optional timeout occurs.

        When the timeout argument is present and not None, it should be a
        floating point number specifying a timeout for the operation in seconds
        (or fractions thereof).

        This method returns the internal flag on exit, so it will always return
        True except if a timeout is given and the operation times out.

        """
        self.__cond.acquire()
        try:
            if not self.__flag:  # start 中执行完毕程序后 self.__flag 是true
                self.__cond.wait(timeout)
            return self.__flag
        finally:
            self.__cond.release()

# Helper to generate new thread names
_counter = _count().next
_counter() # Consume 0 so first non-main thread has id 1.
def _newname(template="Thread-%d"):
    return template % _counter()

# Active thread administration
_active_limbo_lock = _allocate_lock()
_active = {}    # maps thread id to Thread object  用来做活跃的线程映射
_limbo = {}  # 线程对象自己与自己做映射关系 【limbo ：打入冷宫】


# Main class for threads

class Thread(_Verbose):
    """A class that represents a thread of control.

    This class can be safely subclassed in a limited fashion.

    """
    __initialized = False
    # Need to store a reference to sys.exc_info for printing
    # out exceptions when a thread tries to use a global var. during interp.
    # shutdown and thus raises an exception about trying to perform some
    # operation on/with a NoneType
    __exc_info = _sys.exc_info
    # Keep sys.exc_clear too to clear the exception just before
    # allowing .join() to return.
    __exc_clear = _sys.exc_clear

    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, verbose=None):
        """This constructor should always be called with keyword arguments. Arguments are:

        *group* should be None; reserved for future extension when a ThreadGroup
        class is implemented.

        *target* is the callable object to be invoked by the run()
        method. Defaults to None, meaning nothing is called.

        *name* is the thread name. By default, a unique name is constructed of
        the form "Thread-N" where N is a small decimal number.

        *args* is the argument tuple for the target invocation. Defaults to ().

        *kwargs* is a dictionary of keyword arguments for the target
        invocation. Defaults to {}.

        If a subclass overrides the constructor, it must make sure to invoke
        the base class constructor (Thread.__init__()) before doing anything
        else to the thread.

"""
        assert group is None, "group argument must be None for now"
        _Verbose.__init__(self, verbose)
        if kwargs is None:
            kwargs = {}
        self.__target = target
        self.__name = str(name or _newname())
        self.__args = args
        self.__kwargs = kwargs
        self.__daemonic = self._set_daemon()  # 设置是否为守护线程
        self.__ident = None  # 线程的id号，做唯一标识
        self.__started = Event()  # 开始标志位
        self.__stopped = False   # 停止
        self.__block = Condition(Lock())
        self.__initialized = True
        # sys.stderr is not stored in the class like
        # sys.exc_info since it can be changed between instances
        self.__stderr = _sys.stderr

    def _reset_internal_locks(self):
        # private!  Called by _after_fork() to reset our internal locks as
        # they may be in an invalid state leading to a deadlock or crash.
        if hasattr(self, '_Thread__block'):  # DummyThread deletes self.__block
            self.__block.__init__()
        self.__started._reset_internal_locks()

    @property
    def _block(self):
        # used by a unittest
        return self.__block

    def _set_daemon(self):
        # Overridden in _MainThread and _DummyThread
        return current_thread().daemon

    def __repr__(self):
        assert self.__initialized, "Thread.__init__() was not called"
        status = "initial"
        if self.__started.is_set():
            status = "started"
        if self.__stopped:
            status = "stopped"
        if self.__daemonic:
            status += " daemon"
        if self.__ident is not None:
            status += " %s" % self.__ident
        return "<%s(%s, %s)>" % (self.__class__.__name__, self.__name, status)

    def start(self):
        """Start the thread's activity.

        It must be called at most once per thread object. It arranges for the
        object's run() method to be invoked in a separate thread of control.

        This method will raise a RuntimeError if called more than once on the
        same thread object.

        """
        # 每个线程对象最多只能调用一次。 它安排了
        #          对象的run（）方法将在单独的控制线程中调用。
        #          如果多次调用该方法，该方法将引发RuntimeError
        #          相同的线程对象
        if not self.__initialized:
            raise RuntimeError("thread.__init__() not called")
        if self.__started.is_set():
            raise RuntimeError("threads can only be started once")
        if __debug__:
            self._note("%s.start(): starting thread", self)
        with _active_limbo_lock:
            _limbo[self] = self    # start  之后 这个线程就会被打入冷宫
        try:
            _start_new_thread(self.__bootstrap, ())  # 开启一个新的线程（调用的是C的底层部分）
            # self.__bootstrap()  是真正执行多线程目标函数的
        except Exception:
            with _active_limbo_lock:
                del _limbo[self]
            raise
        self.__started.wait()  # 开始时候的等待

    def run(self):
        """Method representing the thread's activity.

        You may override this method in a subclass. The standard run() method
        invokes the callable object passed to the object's constructor as the
        target argument, if any, with sequential and keyword arguments taken
        from the args and kwargs arguments, respectively.

        """

        try:
            if self.__target:
                self.__target(*self.__args, **self.__kwargs)
        finally:
            # Avoid a refcycle if the thread is running a function with
            # an argument that has a member that points to the thread.
            del self.__target, self.__args, self.__kwargs  # 执行完毕后会删除这个执行函数及其一些参数

    def __bootstrap(self):
        # Wrapper around the real bootstrap code that ignores
        # exceptions during interpreter cleanup.  Those typically
        # happen when a daemon thread wakes up at an unfortunate
        # moment, finds the world around it destroyed, and raises some
        # random exception *** while trying to report the exception in
        # __bootstrap_inner() below ***.  Those random exceptions
        # don't help anybody, and they confuse users, so we suppress
        # them.  We suppress them only when it appears that the world
        # indeed has already been destroyed, so that exceptions in
        # __bootstrap_inner() during normal business hours are properly
        # reported.  Also, we only suppress them for daemonic threads;
        # if a non-daemonic encounters this, something else is wrong.

        # ＃在真正的引导程序代码周围包装，在解释器清理期间忽略异常。 这些典型情况发生在守护进程线程在不幸的时刻醒来，
        # 发现周围的世界被破坏，并引发一些随机异常***，同时尝试在***下的__bootstrap_inner（）中报告异常。
        # 那些随机例外对任何人都没有帮助，而且他们混淆了用户，所以我们压制它们。 我们只有在看起来这个世界确实已经被破坏
        # 时才会压制它们，所以正常营业时间内__bootstrap_inner（）中的例外情况会被正确报告。 另外，我们仅仅为了守护线程而
        # 禁止它们;如果一个非守护进程遇到这种情况，那么其他的东西就是错误的。
        try:
            self.__bootstrap_inner()
        except:
            if self.__daemonic and _sys is None:
                return
            raise

    def _set_ident(self):
        self.__ident = _get_ident()

    def __bootstrap_inner(self):
        try:
            self._set_ident()  # 需要执行的线程设置id号
            self.__started.set()  # self.__flag = True  # 标志位设置为True
                                  # self.__cond.notify_all()
            with _active_limbo_lock:
                _active[self.__ident] = self  # 添加此活跃的线程进入映射表中
                del _limbo[self]  # 打入冷宫的删除掉
            if __debug__:
                self._note("%s.__bootstrap(): thread started", self)

            if _trace_hook:
                self._note("%s.__bootstrap(): registering trace hook", self)
                _sys.settrace(_trace_hook)
            if _profile_hook:
                self._note("%s.__bootstrap(): registering profile hook", self)
                _sys.setprofile(_profile_hook)

            try:
                self.run()
            except SystemExit:
                if __debug__:
                    self._note("%s.__bootstrap(): raised SystemExit", self)
            except:
                if __debug__:
                    self._note("%s.__bootstrap(): unhandled exception", self)
                # If sys.stderr is no more (most likely from interpreter
                # shutdown) use self.__stderr.  Otherwise still use sys (as in
                # _sys) in case sys.stderr was redefined since the creation of
                # self.
                if _sys and _sys.stderr is not None:
                    print>>_sys.stderr, ("Exception in thread %s:\n%s" %
                                         (self.name, _format_exc()))
                elif self.__stderr is not None:
                    # Do the best job possible w/o a huge amt. of code to
                    # approximate a traceback (code ideas from
                    # Lib/traceback.py)
                    exc_type, exc_value, exc_tb = self.__exc_info()
                    try:
                        print>>self.__stderr, (
                            "Exception in thread " + self.name +
                            " (most likely raised during interpreter shutdown):")
                        print>>self.__stderr, (
                            "Traceback (most recent call last):")
                        while exc_tb:
                            print>>self.__stderr, (
                                '  File "%s", line %s, in %s' %
                                (exc_tb.tb_frame.f_code.co_filename,
                                    exc_tb.tb_lineno,
                                    exc_tb.tb_frame.f_code.co_name))
                            exc_tb = exc_tb.tb_next
                        print>>self.__stderr, ("%s: %s" % (exc_type, exc_value))
                    # Make sure that exc_tb gets deleted since it is a memory
                    # hog; deleting everything else is just for thoroughness
                    finally:
                        del exc_type, exc_value, exc_tb
            else:
                if __debug__:
                    self._note("%s.__bootstrap(): normal return", self)
            finally:
                # Prevent a race in
                # test_threading.test_no_refcycle_through_target when
                # the exception keeps the target alive past when we
                # assert that it's dead.
                self.__exc_clear()
        finally:
            with _active_limbo_lock:
                self.__stop()
                try:
                    # We don't call self.__delete() because it also
                    # grabs _active_limbo_lock.
                    del _active[_get_ident()]  # 执行完毕后会删除这个活跃的线程
                except:
                    pass

    def __stop(self):
        # DummyThreads delete self.__block, but they have no waiters to
        # notify anyway (join() is forbidden on them).
        # DummyThreads删除self.__块，但他们没有服务员通知（join（）被禁止在他们
        if not hasattr(self, '_Thread__block'):
            return
        self.__block.acquire()
        self.__stopped = True
        self.__block.notify_all()
        self.__block.release()

    def __delete(self):
        "Remove current thread from the dict of currently running threads."

        # Notes about running with dummy_thread:
        #
        # Must take care to not raise an exception if dummy_thread is being
        # used (and thus this module is being used as an instance of
        # dummy_threading).  dummy_thread.get_ident() always returns -1 since
        # there is only one thread if dummy_thread is being used.  Thus
        # len(_active) is always <= 1 here, and any Thread instance created
        # overwrites the (if any) thread currently registered in _active.
        #
        # An instance of _MainThread is always created by 'threading'.  This
        # gets overwritten the instant an instance of Thread is created; both
        # threads return -1 from dummy_thread.get_ident() and thus have the
        # same key in the dict.  So when the _MainThread instance created by
        # 'threading' tries to clean itself up when atexit calls this method
        # it gets a KeyError if another Thread instance was created.
        #
        # This all means that KeyError from trying to delete something from
        # _active if dummy_threading is being used is a red herring.  But
        # since it isn't if dummy_threading is *not* being used then don't
        # hide the exception.

        try:
            with _active_limbo_lock:
                del _active[_get_ident()]
                # There must not be any python code between the previous line
                # and after the lock is released.  Otherwise a tracing function
                # could try to acquire the lock again in the same thread, (in
                # current_thread()), and would block.
        except KeyError:
            if 'dummy_threading' not in _sys.modules:
                raise

    def join(self, timeout=None):
        """Wait until the thread terminates.

        This blocks the calling thread until the thread whose join() method is
        called terminates -- either normally or through an unhandled exception
        or until the optional timeout occurs.

        When the timeout argument is present and not None, it should be a
        floating point number specifying a timeout for the operation in seconds
        (or fractions thereof). As join() always returns None, you must call
        isAlive() after join() to decide whether a timeout happened -- if the
        thread is still alive, the join() call timed out.

        When the timeout argument is not present or None, the operation will
        block until the thread terminates.

        A thread can be join()ed many times.

        join() raises a RuntimeError if an attempt is made to join the current
        thread as that would cause a deadlock. It is also an error to join() a
        thread before it has been started and attempts to do so raises the same
        exception.

        """
        # 等到线程终止。
        # 这会阻塞调用线程，直到其调用join（）方法的线程终止 - 通常或通过未处理的异常或直到发生可选的超时。
        # 当超时参数存在而不是无时，它应该是一个浮点数，以秒为单位指定该操作的超时（或其分数）。 由于join（）总是
        # 返回None，因此必须在join（）之后调用isAlive（）来决定是否发生超时 - 如果线程仍处于活动状态，则join（）调用
        # 超时。 当timeout参数不存在或None时，该操作将阻塞，直到线程终止。 一个线程可以多次join（）。 如果试图加入当前
        # 线程会导致死锁，join（）会引发RuntimeError。 在线程启动之前加入（）线程也是错误的，并且尝试这样做会引发相同的
        # 异常。
        if not self.__initialized:
            raise RuntimeError("Thread.__init__() not called")
        if not self.__started.is_set():
            raise RuntimeError("cannot join thread before it is started")
        if self is current_thread():
            raise RuntimeError("cannot join current thread")

        if __debug__:
            if not self.__stopped:
                self._note("%s.join(): waiting until thread stops", self)
        self.__block.acquire()
        try:
            if timeout is None:
                while not self.__stopped:
                    self.__block.wait()
                if __debug__:
                    self._note("%s.join(): thread stopped", self)
            else:
                deadline = _time() + timeout
                while not self.__stopped:
                    delay = deadline - _time()
                    if delay <= 0:
                        if __debug__:
                            self._note("%s.join(): timed out", self)
                        break
                    self.__block.wait(delay)
                else:
                    if __debug__:
                        self._note("%s.join(): thread stopped", self)
        finally:
            self.__block.release()

    @property
    def name(self):
        """A string used for identification purposes only.

        It has no semantics. Multiple threads may be given the same name. The
        initial name is set by the constructor.

        """
        assert self.__initialized, "Thread.__init__() not called"
        return self.__name

    @name.setter
    def name(self, name):
        assert self.__initialized, "Thread.__init__() not called"
        self.__name = str(name)

    @property
    def ident(self):
        """Thread identifier of this thread or None if it has not been started.

        This is a nonzero integer. See the thread.get_ident() function. Thread
        identifiers may be recycled when a thread exits and another thread is
        created. The identifier is available even after the thread has exited.

        """
        assert self.__initialized, "Thread.__init__() not called"
        return self.__ident

    def isAlive(self):
        """Return whether the thread is alive.

        This method returns True just before the run() method starts until just
        after the run() method terminates. The module function enumerate()
        returns a list of all alive threads.

        """
        assert self.__initialized, "Thread.__init__() not called"
        return self.__started.is_set() and not self.__stopped

    is_alive = isAlive

    @property
    def daemon(self):
        """A boolean value indicating whether this thread is a daemon thread (True) or not (False).

        This must be set before start() is called, otherwise RuntimeError is
        raised. Its initial value is inherited from the creating thread; the
        main thread is not a daemon thread and therefore all threads created in
        the main thread default to daemon = False.

        The entire Python program exits when no alive non-daemon threads are
        left.

        """
        assert self.__initialized, "Thread.__init__() not called"
        return self.__daemonic

    @daemon.setter
    def daemon(self, daemonic):
        if not self.__initialized:
            raise RuntimeError("Thread.__init__() not called")
        if self.__started.is_set():
            raise RuntimeError("cannot set daemon status of active thread");
        self.__daemonic = daemonic

    def isDaemon(self):
        return self.daemon

    def setDaemon(self, daemonic):
        self.daemon = daemonic

    def getName(self):
        return self.name

    def setName(self, name):
        self.name = name

# The timer class was contributed by Itamar Shtull-Trauring

def Timer(*args, **kwargs):
    """Factory function to create a Timer object.

    Timers call a function after a specified number of seconds:

        t = Timer(30.0, f, args=[], kwargs={})
        t.start()
        t.cancel()     # stop the timer's action if it's still waiting

    """
    return _Timer(*args, **kwargs)

class _Timer(Thread):
    """Call a function after a specified number of seconds:

            t = Timer(30.0, f, args=[], kwargs={})
            t.start()
            t.cancel()     # stop the timer's action if it's still waiting

    """

    def __init__(self, interval, function, args=[], kwargs={}):
        Thread.__init__(self)
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.finished = Event()

    def cancel(self):
        """Stop the timer if it hasn't finished yet"""
        self.finished.set()

    def run(self):
        self.finished.wait(self.interval)
        if not self.finished.is_set():
            self.function(*self.args, **self.kwargs)
        self.finished.set()

# Special thread class to represent the main thread
# This is garbage collected through an exit handler

class _MainThread(Thread):

    def __init__(self):
        Thread.__init__(self, name="MainThread")
        self._Thread__started.set()
        self._set_ident()  # 设置唯一标识
        with _active_limbo_lock:
            _active[_get_ident()] = self  # 做id与线程对象的对应映射关系

    def _set_daemon(self):
        return False

    def _exitfunc(self):
        self._Thread__stop()
        t = _pickSomeNonDaemonThread()
        if t:
            if __debug__:
                self._note("%s: waiting for other threads", self)
        while t:
            t.join()
            t = _pickSomeNonDaemonThread()
        if __debug__:
            self._note("%s: exiting", self)
        self._Thread__delete()

def _pickSomeNonDaemonThread():
    for t in enumerate():
        if not t.daemon and t.is_alive():
            return t
    return None


# Dummy thread class to represent threads not started here.
# These aren't garbage collected when they die, nor can they be waited for.
# If they invoke anything in threading.py that calls current_thread(), they
# leave an entry in the _active dict forever after.
# Their purpose is to return *something* from current_thread().
# They are marked as daemon threads so we won't wait for them
# when we exit (conform previous semantics).

class _DummyThread(Thread):  # 虚拟线程(在start时候已执行完毕删除了活跃线程再次执行到join就会执行这个虚拟线程)

    def __init__(self):
        Thread.__init__(self, name=_newname("Dummy-%d"))

        # Thread.__block consumes an OS-level locking primitive, which
        # can never be used by a _DummyThread.  Since a _DummyThread
        # instance is immortal, that's bad, so release this resource.
        del self._Thread__block

        self._Thread__started.set()
        self._set_ident()
        with _active_limbo_lock:
            _active[_get_ident()] = self

    def _set_daemon(self):
        return True

    def join(self, timeout=None):
        assert False, "cannot join a dummy thread"


# Global API functions

def currentThread():
    """Return the current Thread object, corresponding to the caller's thread of control.

    If the caller's thread of control was not created through the threading
    module, a dummy thread object with limited functionality is returned.

    """
    try:
        return _active[_get_ident()]
    except KeyError:
        ##print "current_thread(): no current thread for", _get_ident()
        return _DummyThread()

current_thread = currentThread

def activeCount():
    """Return the number of Thread objects currently alive.

    The returned count is equal to the length of the list returned by
    enumerate().

    """
    with _active_limbo_lock:
        return len(_active) + len(_limbo)

active_count = activeCount

def _enumerate():
    # Same as enumerate(), but without the lock. Internal use only.
    return _active.values() + _limbo.values()

def enumerate():
    """Return a list of all Thread objects currently alive.

    The list includes daemonic threads, dummy thread objects created by
    current_thread(), and the main thread. It excludes terminated threads and
    threads that have not yet been started.

    """
    with _active_limbo_lock:
        return _active.values() + _limbo.values()

from thread import stack_size

# Create the main thread object,
# and make it available for the interpreter
# (Py_Main) as threading._shutdown.

_shutdown = _MainThread()._exitfunc

# get thread-local implementation, either from the thread
# module, or from the python fallback

try:
    from thread import _local as local
except ImportError:
    from _threading_local import local


def _after_fork():
    # This function is called by Python/ceval.c:PyEval_ReInitThreads which
    # is called from PyOS_AfterFork.  Here we cleanup threading module state
    # that should not exist after a fork.

    # Reset _active_limbo_lock, in case we forked while the lock was held
    # by another (non-forked) thread.  http://bugs.python.org/issue874900
    global _active_limbo_lock
    _active_limbo_lock = _allocate_lock()

    # fork() only copied the current thread; clear references to others.
    new_active = {}
    current = current_thread()
    with _active_limbo_lock:
        for thread in _enumerate():
            # Any lock/condition variable may be currently locked or in an
            # invalid state, so we reinitialize them.
            if hasattr(thread, '_reset_internal_locks'):
                thread._reset_internal_locks()
            if thread is current:
                # There is only one active thread. We reset the ident to
                # its new value since it can have changed.
                ident = _get_ident()
                thread._Thread__ident = ident
                new_active[ident] = thread
            else:
                # All the others are already stopped.
                thread._Thread__stop()

        _limbo.clear()
        _active.clear()
        _active.update(new_active)
        assert len(_active) == 1





# Self-test code


def _test():

    class BoundedQueue(_Verbose):

        def __init__(self, limit):
            _Verbose.__init__(self)
            self.mon = RLock()
            self.rc = Condition(self.mon)  #  # Condition（条件变量）通常与一个锁关联。需要在多个Contidion中共享一个锁时，
            # 可以传递一个Lock/RLock实例给构造方法，否则它将自己生成一个RLock实例
            # 可以认为，除了Lock带有的锁定池外，Condition还包含一个【等待池】，池中的线程处于等待阻塞状态，
            # 直到另一个线程调用notify()/notifyAll()通知；得到通知后线程进入锁定池[等待锁定]。
            self.wc = Condition(self.mon)
            self.limit = limit
            self.queue = _deque()

        def put(self, item):
            self.mon.acquire()
            while len(self.queue) >= self.limit:
                self._note("put(%s): queue full", item)
                self.wc.wait()
            self.queue.append(item)
            self._note("put(%s): appended, length now %d",
                       item, len(self.queue))
            self.rc.notify()
            self.mon.release()

        def get(self):
            self.mon.acquire()
            while not self.queue:
                self._note("get(): queue empty")
                self.rc.wait()
            item = self.queue.popleft()
            self._note("get(): got %s, %d left", item, len(self.queue))
            self.wc.notify()
            self.mon.release()
            return item

    class ProducerThread(Thread):

        def __init__(self, queue, quota):
            Thread.__init__(self, name="Producer")
            self.queue = queue
            self.quota = quota

        def run(self):
            from random import random
            counter = 0
            while counter < self.quota:
                counter = counter + 1
                self.queue.put("%s.%d" % (self.name, counter))
                _sleep(random() * 0.00001)


    class ConsumerThread(Thread):

        def __init__(self, queue, count):
            Thread.__init__(self, name="Consumer")
            self.queue = queue
            self.count = count

        def run(self):
            while self.count > 0:
                item = self.queue.get()
                print item
                self.count = self.count - 1

    NP = 2
    QL = 4
    NI = 5

    Q = BoundedQueue(QL)
    P = []
    print '1'
    for i in range(NP):
        t = ProducerThread(Q, NI)
        t.name = ("Producer-%d" % (i+1))
        P.append(t)
    C = ConsumerThread(Q, NI*NP)

    for t in P:
        t.start()
        _sleep(0.000001)
    C.start()
    for t in P:
        t.join()

    C.join()
    print '2'

if __name__ == '__main__':
    _test()

    # Condition类
    # acquire([timeout]) / release(): 调用关联的锁的相应方法。
    # wait([timeout]): 调用这个方法将使线程进入Condition的等待池等待通知，并释放锁。使用前线程必须已获得锁定，否则将抛出异常。
    # notify(): 调用这个方法将从[等待池]挑选一个线程并通知，收到通知的线程将自动调用acquire()
    # 尝试获得锁定（进入锁定池）；其他线程仍然在等待池中。调用这个方法不会释放锁定。使用前线程必须已获得锁定，否则将抛出异常。
    # notifyAll(): 调用这个方法将通知等待池中所有的线程，这些线程都将进入锁定池尝试获得锁定。调用这个方法不会释放锁定。使用前线程必须已获得锁定，否则将抛出异常。

    # Event类
    # Event（事件）是最简单的【线程通信机制】之一：一个线程通知事件，其他线程等待事件。Event内置了一个初始为False的标志，
    # 当调用set()时设为True，调用clear()时重置为 False。wait()将阻塞线程至等待阻塞状态。
    # Event其实就是一个简化版的 Condition。Event没有锁，无法使线程进入同步阻塞状态。
    # isSet(): 当内置标志为True时返回True。
    # set(): 将标志设为True，并通知所有处于等待阻塞状态的线程恢复运行状态。
    # clear(): 将标志设为False。
    # wait([timeout]): 如果标志为True将立即返回，否则阻塞线程至等待阻塞状态，等待其他线程调用set()。

    # timer类
    # Timer（定时器）是Thread的派生类，用于在指定时间后调用一个方法。
    # 构造方法：
    # Timer(interval, function, args=[], kwargs={})
    # 　　interval: 指定的时间
    # 　　function: 要执行的方法
    # 　　args/kwargs: 方法的参数
    #
    # 实例方法：
    # Timer从Thread派生，没有增加实例方法。

    # local类
    # local是一个小写字母开头的类，用于管理
    # thread - local（线程局部的）数据。对于同一个local，线程无法访问其他线程设置的属性；线程设置的属性不会被其他线程设置的同名属性替换。
    # 可以把local看成是一个“线程 - 属性字典”的字典，local封装了从自身使用线程作为
    # key检索对应的属性字典、再使用属性名作为key检索属性值的细节。


    # RLock（可重入锁）是一个可以被同一个线程请求多次的同步指令。RLock使用了“拥有的线程”和“递归等级”的概念，处于锁定状态时，RLock被某个线程拥有。
    # 拥有RLock的线程可以再次调用acquire()，释放锁时需要调用release()相同次数。

    # threading.Event()
    # 一个工厂函数，返回一个新的event对象。一个event管理一个标志，该标志可以通过set()方法设置为真或通过clear()方法重新设置为假。wait()方法将阻塞直至该标志为真。


    # threading.Condition
    # 可以把Condiftion理解为一把高级的琐，它提供了比Lock, RLock更高级的功能，允许我们能够控制复杂的线程同步问题。
    # threadiong.Condition在内部维护一个琐对象（默认是RLock），可以在创建Condigtion对象的时候把琐对象作为参数传入。
    # Condition也提供了acquire, release方法，其含义与琐的acquire, release方法一致，其实它只是简单的调用内部琐对象的对应的方法而已。
    # Condition还提供了如下方法(特别要注意：这些方法只有在占用琐(acquire)之后才能调用，否则将会报RuntimeError异常。)：

    # Condition.wait([timeout]):
    # wait方法释放内部所占用的琐，同时线程被挂起，直至接收到通知被唤醒或超时（如果提供了timeout参数的话）。
    # 当线程被唤醒并重新占有琐的时候，程序才会继续执行下去。

    # Condition.notify():
    # 唤醒一个挂起的线程（如果存在挂起的线程）。注意：notify()方法不会释放所占用的琐。