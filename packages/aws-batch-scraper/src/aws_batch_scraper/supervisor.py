"""Keep browser deadlines outside the process that can swallow or block them."""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import signal
import socket
import struct
import time
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from typing import Any

from aws_batch_scraper.types import FailureArtifact, Scraper, ScrapeResult, WorkItem

_MAX_FRAME_BYTES = 32 * 1024 * 1024


class ScraperProcessError(RuntimeError):
    """The worker must exit so Fargate also reaps any orphan browser descendants."""


class ScraperProcessTimeout(ScraperProcessError):
    """A scrape, reset, startup, or teardown exceeded its external deadline."""


def _send(channel: socket.socket, value: object) -> None:
    body = json.dumps(value, allow_nan=False).encode()
    if len(body) > _MAX_FRAME_BYTES:
        raise ValueError("Scraper IPC frame exceeds its size limit")
    channel.sendall(struct.pack("!I", len(body)) + body)


def _receive(channel: socket.socket, deadline: float | None = None) -> Any:
    def read(size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError("Scraper IPC deadline expired")
            channel.settimeout(remaining)
            chunk = channel.recv(size - len(chunks))
            if not chunk:
                raise EOFError("Scraper process closed its channel")
            chunks.extend(chunk)
        return bytes(chunks)

    size = struct.unpack("!I", read(4))[0]
    if size > _MAX_FRAME_BYTES:
        raise ValueError("Scraper IPC frame exceeds its size limit")
    return json.loads(read(size))


def _serve(channel: socket.socket, factory: Callable[[], Scraper]) -> None:
    # A clean spawned interpreter does not inherit the worker's boto clients or
    # signal handlers. Browser reuse stays inside this one process.
    os.setsid()
    scraper = factory()
    try:
        _send(channel, {"ok": True, "value": None})
        while True:
            request = _receive(channel)
            operation = request["operation"]
            try:
                if operation == "scrape":
                    item = WorkItem(**request["item"])
                    value = scraper(item).model_dump(mode="json")
                elif operation == "artifacts":
                    getter = getattr(scraper, "failure_artifacts", None)
                    artifacts = getter(WorkItem(**request["item"])) if callable(getter) else []
                    value = [
                        {
                            "suffix": artifact.suffix,
                            "body": base64.b64encode(artifact.body).decode("ascii"),
                            "content_type": artifact.content_type,
                        }
                        for artifact in artifacts
                    ]
                elif operation == "reset":
                    scraper.reset()
                    value = None
                elif operation == "close":
                    scraper.close()
                    _send(channel, {"ok": True, "value": None})
                    return
                else:
                    raise ValueError("Unknown scraper operation")
                _send(channel, {"ok": True, "value": value})
            except Exception as exc:
                # Exception text can contain page data or credentials. The parent
                # needs a bounded failure category, never a pickled exception.
                _send(channel, {"ok": False, "error_type": type(exc).__name__})
    finally:
        channel.close()


class SupervisedScraper:
    """Reuse a browser child while the parent enforces every operation deadline.

    A failed deadline is fatal to the ECS worker, rather than repeatedly spawning
    children beside possibly orphaned Chrome processes. The SQS receipt is left
    unacknowledged for redelivery; same-run recovery can replace the stopped task.
    """

    def __init__(
        self,
        factory: Callable[[], Scraper],
        *,
        scrape_timeout: float = 300,
        control_timeout: float = 30,
        stop_grace: float = 2,
    ) -> None:
        if min(scrape_timeout, control_timeout, stop_grace) <= 0:
            raise ValueError("Supervisor deadlines must be positive")
        self.factory = factory
        self.scrape_timeout = scrape_timeout
        self.control_timeout = control_timeout
        self.stop_grace = stop_grace
        self._process: BaseProcess | None = None
        self._channel: socket.socket | None = None
        self._failed = False

    def _start(self) -> None:
        if self._failed:
            raise ScraperProcessError("Scraper process failed; worker restart is required")
        if self._process is not None:
            return
        parent, child = socket.socketpair()
        process = multiprocessing.get_context("spawn").Process(
            target=_serve, args=(child, self.factory), name="scraper-browser"
        )
        self._process, self._channel = process, parent
        try:
            try:
                process.start()
            finally:
                child.close()
            self._response(time.monotonic() + self.control_timeout)
        except BaseException:
            self._abort()
            raise

    def _abort(self) -> None:
        self._failed = True
        process, self._process = self._process, None
        channel, self._channel = self._channel, None
        if channel is not None:
            channel.close()
        if process is None or process.pid is None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            if process.is_alive():
                process.terminate()
        process.join(self.stop_grace)
        # Kill the group even when the leader exited but left descendants.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if process.is_alive():
                process.kill()
        process.join(self.stop_grace)
        if process.is_alive():
            raise ScraperProcessError("Scraper child could not be stopped")
        process.close()

    def _response(self, deadline: float) -> Any:
        if self._channel is None:
            raise ScraperProcessError("Scraper channel is unavailable")
        try:
            response = _receive(self._channel, deadline)
        except TimeoutError as exc:
            raise ScraperProcessTimeout("Scraper process exceeded its deadline") from exc
        except (EOFError, OSError, ValueError) as exc:
            raise ScraperProcessError("Scraper process returned no valid response") from exc
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise ScraperProcessError("Scraper process reported an operation failure")
        return response.get("value")

    def _request(self, operation: str, item: WorkItem | None, timeout: float) -> Any:
        self._start()
        if self._channel is None:
            raise ScraperProcessError("Scraper channel is unavailable")
        deadline = time.monotonic() + timeout
        try:
            self._channel.settimeout(timeout)
            _send(
                self._channel,
                {
                    "operation": operation,
                    "item": None
                    if item is None
                    else {"item_id": item.item_id, "extra": item.extra},
                },
            )
            return self._response(deadline)
        except BaseException:
            self._abort()
            raise

    def __call__(self, item: WorkItem) -> ScrapeResult:
        return ScrapeResult.model_validate(self._request("scrape", item, self.scrape_timeout))

    def failure_artifacts(self, item: WorkItem) -> list[FailureArtifact]:
        return [
            FailureArtifact(
                suffix=value["suffix"],
                body=base64.b64decode(value["body"], validate=True),
                content_type=value["content_type"],
            )
            for value in self._request("artifacts", item, self.control_timeout)
        ]

    def reset(self) -> None:
        self._request("reset", None, self.control_timeout)

    def close(self) -> None:
        if self._process is not None:
            try:
                self._request("close", None, self.control_timeout)
            finally:
                self._abort()
