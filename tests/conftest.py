from __future__ import annotations

import inspect
import logging
import os
from typing import Iterator, List

import pyalect.builtins.pytest  # noqa
import pytest
from _pytest.config import Config
from _pytest.config.argparsing import Parser
from _pytest.logging import LogCaptureFixture
from _pytest.logging import caplog as _caplog  # noqa
from loguru import logger
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait

import idom
from idom.client import manage as manage_client
from idom.testing import ServerMountPoint, create_simple_selenium_web_driver


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.config.Config, items: List[pytest.Item]
) -> None:
    _mark_coros_as_async_tests(items)
    _skip_web_driver_tests_on_windows(items)


def pytest_addoption(parser: Parser) -> None:
    parser.addoption(
        "--headless",
        dest="headless",
        action="store_true",
        help="Whether to run browser tests in headless mode.",
    )
    parser.addoption(
        "--no-restore",
        dest="restore_client",
        action="store_false",
        help="Whether to restore the client build before testing.",
    )


@pytest.fixture
def display(driver, server_mount_point):
    display_id = idom.Ref(0)

    def mount_and_display(component_constructor, query=None, check_mount=True):
        component_id = f"display-{display_id.set_current(display_id.current + 1)}"
        server_mount_point.mount(
            lambda: idom.html.div({"id": component_id}, component_constructor())
        )
        driver.get(server_mount_point.url(query=query))
        if check_mount:
            driver.find_element_by_id(component_id)
        return component_id

    yield mount_and_display


@pytest.fixture
def driver_get(driver, server_mount_point):
    return lambda query=None: driver.get(server_mount_point.url(query=query))


@pytest.fixture
def server_mount_point():
    """An IDOM layout mount function and server as a tuple

    The ``mount`` and ``server`` fixtures use this.
    """
    with ServerMountPoint(server_config={"cors": True}) as mount_point:
        yield mount_point


@pytest.fixture(scope="module")
def driver_wait(driver):
    return WebDriverWait(driver, 3)


@pytest.fixture(scope="module")
def driver(create_driver) -> Chrome:
    """A Selenium web driver"""
    return create_driver()


@pytest.fixture(scope="module")
def create_driver(driver_is_headless):
    """A Selenium web driver"""
    drivers = []

    def create():
        options = ChromeOptions()
        options.headless = driver_is_headless
        driver = create_simple_selenium_web_driver(driver_options=options)
        drivers.append(driver)
        return driver

    yield create

    for d in drivers:
        d.quit()


@pytest.fixture(scope="session")
def driver_is_headless(pytestconfig: Config):
    return bool(pytestconfig.option.headless)


@pytest.fixture(autouse=True)
def caplog(_caplog: LogCaptureFixture) -> Iterator[LogCaptureFixture]:
    handler_id = logger.add(_PropogateHandler(), format="{message}")
    yield _caplog
    logger.remove(handler_id)
    for record in _caplog.records:
        if record.exc_info:
            raise record.exc_info[1]
        assert record.levelno < logging.ERROR


class _PropogateHandler(logging.Handler):
    def emit(self, record):
        logging.getLogger(record.name).handle(record)


@pytest.fixture(scope="session", autouse=True)
def _restore_client(pytestconfig: Config) -> Iterator[None]:
    """Restore the client's state before and after testing

    For faster test runs set ``--no-restore-client`` at the CLI. Test coverage and
    breakages may occur if this is set. Further the client is not cleaned up
    after testing and may effect usage of IDOM beyond the scope of the tests.
    """
    if pytestconfig.option.restore_client:
        manage_client.restore()
        yield
        manage_client.restore()
    else:
        yield


def _mark_coros_as_async_tests(items: List[pytest.Item]) -> None:
    for item in items:
        if isinstance(item, pytest.Function):
            if inspect.iscoroutinefunction(item.function):
                item.add_marker(pytest.mark.asyncio)


def _skip_web_driver_tests_on_windows(items: List[pytest.Item]) -> None:
    if os.name == "nt":
        for item in items:
            if isinstance(item, pytest.Function):
                if {"display", "driver", "create_driver"}.intersection(
                    item.fixturenames
                ):
                    item.add_marker(
                        pytest.mark.skip(
                            reason="WebDriver tests are not working on Windows",
                        )
                    )
