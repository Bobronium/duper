"""
Render console output + HTML where lines expand with profiler results

Howto:
Parse function source into ast tree
extract expressions by lines
handle cases such as try: ...; except: pass as single expression
(check all linenos of expression and if any of them contain # t comment, include them)
(we probably don't even need iPython for this, and it might be simpler just to do all the work by ourselves)
though PoC was easier to write with iPython
"""
import math

import inspect
import sys
import textwrap
import traceback
from functools import partial
from types import CodeType, GenericAlias

import pyinstrument
from IPython import InteractiveShell

from IPython.core.magics.execution import TimeitResult
from pygments.styles.gh_dark import GhDarkStyle
from pyinstrument.frame import Frame
from pyinstrument.frame_ops import FrameRecordType
from pyinstrument.renderers import ConsoleRenderer
from pyinstrument.renderers.base import ProcessorList
from pyinstrument.session import Session


def _timer_magic():
    ...


from typing import Any, AbstractSet, Set, Iterator, Iterable, TypeVar

from pygments import highlight
from pygments.formatters import Terminal256Formatter
from pygments.lexers import PythonLexer


class InlineRenderer(ConsoleRenderer):
    def render_preamble(self, session: Session):
        return ""

    def render_frame(self, frame: Frame, indent: str = "    ", child_indent: str = "    ") -> str:
        ".group.exit_frames[0].children[0]"
        if self.root_frame is frame:
            # locations = ["children", 0, "group", "exit_frames", 0, "children", 0]
            # while frame and locations:
            #     location = locations.pop(0)
            #     new_frame = getattr(frame, location) if isinstance(location, str) else frame[location]
            #     if not new_frame:
            #         break
            #     frame = new_frame
            self.root_frame = frame
            if not frame:
                return indent + "No frames were recorded"
        return super().render_frame(frame, indent, child_indent)


from pygments.styles.monokai import MonokaiStyle


def colorize(*code, sep=""):
    return highlight(
        sep.join(code), PythonLexer(), Terminal256Formatter(style=MonokaiStyle)
    ).removesuffix("\n")


def pprint_line(*obj: Any, start="    ", end="\n", sep="") -> None:
    """Pretty-print in color."""
    print(start + colorize(*obj, sep=sep), end=end)


def _format_time(timespan, precision=3):
    """Formats the timespan in a human readable form"""

    if timespan >= 60.0:
        # we have more than a minute, format that in a human readable form
        # Idea from http://snipplr.com/view/5713/
        parts = [("d", 60 * 60 * 24), ("h", 60 * 60), ("min", 60), ("s", 1)]
        time = []
        leftover = timespan
        for suffix, length in parts:
            value = int(leftover / length)
            if value > 0:
                leftover = leftover % length
                time.append("%s%s" % (str(value), suffix))
            if leftover < 1:
                break
        return " ".join(time)

    # Unfortunately the unicode 'micro' symbol can cause problems in
    # certain terminals.
    # See bug: https://bugs.launchpad.net/ipython/+bug/348466
    # Try to prevent crashes by being more secure than it needs to
    # E.g. eclipse is able to print a µ, but has no sys.stdout.encoding set.
    units = ["s", "ms", "us", "ns"]  # the save value
    if hasattr(sys.stdout, "encoding") and sys.stdout.encoding:
        try:
            "\xb5".encode(sys.stdout.encoding)
            units = ["s", "ms", "\xb5s", "ns"]
        except:
            pass
    scaling = [1, 1e3, 1e6, 1e9]

    if timespan > 0.0:
        order = min(-int(math.floor(math.log10(timespan)) // 3), 3)
    else:
        order = 3
    return "%.*g %s" % (precision, timespan * scaling[order], units[order])


def _patch_shell_exc_info(shell, function, line_offset):
    """
    Injects a _render_traceback method into exceptions caught in the shell

    This is a terrible hack, and there's certainly a better solution, but this is the first thing
    I came up with
    """
    orig = shell._get_exc_info

    def _get_line(n):
        return inspect.getsourcelines(sys.modules[function.__module__])[0][n - 1]

    def _get_exc_info(exc_tuple=None):
        def render_traceback():
            frames = traceback.extract_tb(tb.tb_next)  # skip frame with exec() from IPython
            for frame in frames:
                if not frame.filename.startswith("<ipython-input"):
                    continue
                frame.lineno += line_offset - 1
                frame.name = function.__name__
                frame.filename = function.__code__.co_filename
                frame._line = _get_line(frame.lineno)

            return [
                "\n",
                colorize(
                    "Traceback (most recent call last):\n",
                    *frames.format(),
                    *traceback.TracebackException(etype, value, tb).format_exception_only(),
                ),
            ]

        etype, value, tb = orig(exc_tuple)
        value._render_traceback_ = render_traceback
        return etype, value, tb

    shell._get_exc_info = _get_exc_info


def run(function, profile=True, repeats=7, number=None):
    if function.__code__.co_argcount:
        raise RuntimeError(f"function {function.__qualname__} cannot have any arguments")

    c: CodeType = function.__code__

    # executor = ExecutionMagics(shell)
    decorators = []
    code_lines = []
    body_starts_at = None
    longest_line_length = 0
    for i, line in enumerate(inspect.getsource(function).splitlines(keepends=True)):
        if "# t" in line and not line.lstrip().startswith("#"):
            longest_line_length = max(len(line[: line.find("# t")]), longest_line_length)
        if body_starts_at:  # skip decorators
            code_lines.append(line)
        elif line.strip().startswith("def "):
            body_starts_at = i
            continue
        else:
            decorators.append(line)

    code_lines = textwrap.dedent("".join(code_lines))
    lines_offset = c.co_firstlineno - body_starts_at + 3
    executable_lines = {lineno - lines_offset for _, _, lineno in function.__code__.co_lines()}

    pprint_line("".join(decorators).strip(), start="")
    pprint_line(f"def {function.__name__}():", start="")

    # init shell
    shell = InteractiveShell()
    # update shall with function __globals__
    #
    shell.user_global_ns.update(function.__globals__)
    _patch_shell_exc_info(shell, function, lines_offset)

    current_statement = []
    results = {}
    for i, line in enumerate(code_lines.splitlines()):
        current_statement.append(line)
        if "# i" in line or not line or line.lstrip().startswith("#"):
            end = line.find("# i")
            if end == -1:
                end = None
            pprint_line(line[:end])
        if i not in executable_lines:
            continue
        if "# t" in line or not longest_line_length and "# i" not in line:
            try:
                output_line, params = line.split("# t")
            except ValueError:
                output_line = line
                params = ""
            match params.split():
                case [case_name, compare_to]:
                    ...
                case [case_name]:
                    compare_to = case_name.removeprefix("?") if case_name.startswith("?") else None
                    case_name = None if compare_to else case_name
                case []:
                    compare_to = case_name = None
                case _:
                    raise NotImplementedError(f"Can't parse {line}")

            if case_name is not None and case_name in results:
                raise NameError(f"case {case_name} was already defined above")
            if compare_to is not None:
                try:
                    compare_to_result = results[compare_to]
                except KeyError:
                    raise NameError(f"Can't compare to {compare_to!r}, case is not defined")
            else:
                compare_to_result = None

            pprint_line(output_line, end=" " * (longest_line_length - len(output_line) - 4) + "# ")
            # run timeit first
            if profile:
                profiler = pyinstrument.Profiler(interval=0.001)
                profiler.start()
            try:
                n = ""
                if number is not None:
                    n = f"-n {number}"

                result: TimeitResult = shell.run_line_magic(
                    "timeit", f"-q -o {n} -r {repeats} {line}"
                )
            except Exception:
                raise
                pass  # we'll deal with it below, when executing the line in shell context
            else:
                if profile:
                    profiler.stop()
                results[case_name] = result
                # so much for private code...
                # TODO: should probably just vendor these parts
                out = f"~{result.best * 1000:.5F} ms"
                if case_name:
                    out += f" ({case_name})"
                if compare_to_result:
                    if compare_to_result.best > result.best:
                        out += f": {compare_to_result.best / result.best:.2F} times faster than {compare_to}"
                    else:
                        out += f": {result.best / compare_to_result.best:.2F} times slower than {compare_to}"
                # result = "{mean}".format(
                #     mean=,
                #     std=_format_time(self.stdev, self._precision),
                # )
                pprint_line(str(out), start="")
                fr: FrameRecordType
                if profile:
                    # root = profiler.last_session.root_frame(trim_stem=False)
                    print(InlineRenderer(color=True, show_all=True).render(profiler.last_session))

        out = shell.run_cell("\n".join(current_statement), silent=True)
        if not out.success:
            return

    return


def timesup(*fn, profile=False, repeats=7, number=None):
    if not fn:
        return partial(timesup, profile=profile, repeats=repeats, number=number)
    assert len(fn) == 1

    # def proxy():
    run(*fn, profile=profile, repeats=repeats, number=number)

    # return proxy


class C:
    pass
