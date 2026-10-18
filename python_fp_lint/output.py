# python_fp_lint/output.py
"""The CLI's two channels: output written by emit(), diagnostics via logging.

Output is what a command produces -- a report, JSON, the hook's block message
-- and its exact bytes are a contract with whoever reads them. It never goes
through logging, which can be reformatted or silenced by any logging config.
Diagnostics (an `error: ...` line before exiting 2) are logged under the
`python_fp_lint` logger, which configure_cli_logging() prints as the bare
message.
"""

import logging
import sys
from enum import Enum, auto


class Stream(Enum):
    STDOUT = auto()
    STDERR = auto()


def emit(text: str = "", stream: Stream = Stream.STDOUT) -> None:
    """Write one line of command output."""
    target = sys.stdout if stream is Stream.STDOUT else sys.stderr
    target.write(text + "\n")


class _CurrentStderrHandler(logging.Handler):
    """Writes to whatever sys.stderr is at emit time, not at construction, so
    a redirected or captured stderr still receives the message."""

    def emit(self, record: logging.LogRecord) -> None:
        sys.stderr.write(self.format(record) + "\n")


def configure_cli_logging() -> None:
    """Print the package's log records as bare lines on stderr. Idempotent."""
    logger = logging.getLogger("python_fp_lint")
    if any(isinstance(h, _CurrentStderrHandler) for h in logger.handlers):
        return
    logger.addHandler(_CurrentStderrHandler())
    logger.setLevel(logging.INFO)
    # The CLI owns these lines; a host application's root handlers must not
    # print them a second time in their own format.
    logger.propagate = False
