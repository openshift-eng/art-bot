import asyncio
import functools
import os
import shlex
import subprocess
import time
import traceback
from fcntl import fcntl, F_GETFL, F_SETFL
from typing import Union, List, Tuple

from artbotlib import variables as variables
from artbotlib.formatting import extract_plain_text

from artbotlib.util import logger


async def cmd_gather_async(cmd: Union[List[str], str], check: bool = True, **kwargs) -> Tuple[int, str, str]:
    """ Runs a command asynchronously and returns rc,stdout,stderr as a tuple
    :param cmd: A shell command
    :param check: If check is True and the exit code was non-zero, it raises a ChildProcessError
    :param kwargs: Other arguments passing to asyncio.subprocess.create_subprocess_exec
    :return: rc,stdout,stderr
    """

    logger.info(f'Running async command: {cmd}')

    if isinstance(cmd, str):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    # capture stdout and stderr if they are not set in kwargs
    if "stdout" not in kwargs:
        kwargs["stdout"] = asyncio.subprocess.PIPE
    if "stderr" not in kwargs:
        kwargs["stderr"] = asyncio.subprocess.PIPE

    # Execute command asynchronously
    proc = await asyncio.subprocess.create_subprocess_exec(cmd_list[0], *cmd_list[1:], **kwargs)
    stdout, stderr = await proc.communicate()
    stdout = stdout.decode() if stdout else ""
    stderr = stderr.decode() if stderr else ""
    if proc.returncode != 0:
        msg = f"Process {cmd_list!r} exited with code {proc.returncode}.\nstdout>>{stdout}<<\nstderr>>{stderr}<<\n"
        if check:
            raise ChildProcessError(msg)
        else:
            logger.warning(msg)
    return proc.returncode, stdout, stderr


def limit_concurrency(limit=5):
    """A decorator to limit the number of parallel tasks with asyncio.

    It should be noted that when the decorator function is executed, the created Semaphore is bound to the default event loop.
    https://stackoverflow.com/a/66289885
    """

    # use asyncio.BoundedSemaphore(5) instead of Semaphore to prevent
    # accidentally increasing the original limit (stackoverflow.com/a/48971158/6687477)
    sem = asyncio.BoundedSemaphore(limit)

    def executor(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async with sem:
                return await func(*args, **kwargs)

        return wrapper

    return executor


def cmd_gather(cmd, set_env=None, cwd=None, realtime=False):
    """
    Runs a command and returns rc,stdout,stderr as a tuple.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :param cwd: The directory from which to run the command
    :param set_env: Dict of env vars to set for command (overriding existing)
    :param realtime: If True, output stdout and stderr in realtime instead of all at once.
    :return: (rc,stdout,stderr)
    """

    if not isinstance(cmd, list):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    cmd_info = '[cwd={}]: {}'.format(cwd, cmd_list)

    env = os.environ.copy()
    if set_env:
        cmd_info = '[env={}] {}'.format(set_env, cmd_info)
        env.update(set_env)

    # Make sure output of launched commands is utf-8
    env['LC_ALL'] = 'en_US.UTF-8'

    logger.debug("Executing:cmd_gather {}".format(cmd_info))
    try:
        proc = subprocess.Popen(
            cmd_list, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        logger.error("Subprocess errored running:\n{}\nWith error:\n{}\nIs {} installed?".format(
            cmd_info, exc, cmd_list[0]
        ))
        return exc.errno, "", "Subprocess errored running:\n{}\nWith error:\n{}\nIs {} installed?".format(
            cmd_info, exc, cmd_list[0]
        )

    if not realtime:
        out, err = proc.communicate()
        rc = proc.returncode
    else:
        out = b''
        err = b''

        # Many thanks to http://eyalarubas.com/python-subproc-nonblock.html
        # setup non-blocking read
        # set the O_NONBLOCK flag of proc.stdout file descriptor:
        flags = fcntl(proc.stdout, F_GETFL)  # get current proc.stdout flags
        fcntl(proc.stdout, F_SETFL, flags | os.O_NONBLOCK)
        # set the O_NONBLOCK flag of proc.stderr file descriptor:
        flags = fcntl(proc.stderr, F_GETFL)  # get current proc.stderr flags
        fcntl(proc.stderr, F_SETFL, flags | os.O_NONBLOCK)

        rc = None
        while rc is None:
            try:
                output = os.read(proc.stdout.fileno(), 256)
                logger.info(f'{cmd_info} stdout: {out.rstrip()}')
                out += output
            except OSError:
                pass

            try:
                error = os.read(proc.stderr.fileno(), 256)
                logger.warning(f'{cmd_info} stderr: {error.rstrip()}')
                out += error
            except OSError:
                pass

            rc = proc.poll()
            time.sleep(0.0001)  # reduce busy-wait

    # We read in bytes representing utf-8 output; decode so that python recognizes them as unicode strings
    out = out.decode('utf-8')
    err = err.decode('utf-8')
    logger.debug(
        "Process {}: exited with: {}\nstdout>>{}<<\nstderr>>{}<<\n".
        format(cmd_info, rc, out, err))
    return rc, out, err


def cmd_assert(so, cmd, set_env=None, cwd=None, realtime=False):
    """
    A cmd_gather invocation, but if it fails, it will notify the
    alert the monitoring channel and the requesting user with
    information about the failure.
    :return:
    """

    error_id = f'{so.from_user_id()}.{int(time.time() * 1000)}'

    def send_cmd_error(rc, stdout, stderr):
        intro = f'Error running command (for user={so.from_user_mention()} error-id={error_id}): {cmd}'
        payload = f"rc={rc}\n\nstdout={stdout}\n\nstderr={stderr}\n"
        so.monitoring_snippet(intro=intro, filename='cmd_error.log', payload=payload)

    try:
        rc, stdout, stderr = cmd_gather(cmd, set_env, cwd, realtime)
    except subprocess.CalledProcessError as exec:
        send_cmd_error(exec.returncode, exec.stdout, exec.stderr)
        raise
    except Exception:
        send_cmd_error(-1000, '', traceback.format_exc())
        raise

    if rc:
        logger.warning(f'error-id={error_id} . Non-zero return code from: {cmd}\nStdout:\n{stdout}\n\nStderr:\n{stderr}\n')
        send_cmd_error(rc, stdout, stderr)
        so.say(f'Sorry, but I encountered an error. Details have been sent to the ART team. Mention error-id={error_id} when requesting support.')
        raise IOError(f'Non-zero return code from: {cmd}')

    return rc, stdout, stderr


def sigterm_handler(_signo, _stack_frame):
    """
    Function to handle SIGTERM signal sent during pod termination. Check if long running requests are still running.
    If any, report to the user saying that they have re-run the command.
    """

    slack_objects = variables.active_slack_objects
    for slack_object in slack_objects:
        plain_text = extract_plain_text({"data": slack_object.event})
        slack_object.say(f"Uh oh... art-bot is restarting. Please try *'{plain_text}'* again, after a minute.")
