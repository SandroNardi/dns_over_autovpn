import errno

import pytest

from server import (
    DEFAULT_PORT,
    PORT_SPAN,
    address_in_use,
    band_busy_message,
    bind_loopback,
    parse_args,
    ports_to_try,
    startup_message,
)


def _busy(port):
    exc = OSError("busy")
    exc.errno = errno.EADDRINUSE
    exc.winerror = 10048
    return exc


def test_default_walks_the_band_in_order():
    tried = []

    def bind(port):
        tried.append(port)
        if port < DEFAULT_PORT + 2:
            raise _busy(port)
        return f"server-{port}"

    server, port, skipped = bind_loopback(ports_to_try(None), bind)
    assert tried == [DEFAULT_PORT, DEFAULT_PORT + 1, DEFAULT_PORT + 2]
    assert server == f"server-{DEFAULT_PORT + 2}"
    assert port == DEFAULT_PORT + 2
    assert skipped == [DEFAULT_PORT, DEFAULT_PORT + 1]
    url, message = startup_message(port, skipped)
    assert url == f"http://127.0.0.1:{port}/"
    assert str(DEFAULT_PORT) in message
    assert f"using {port}" in message


def test_port_outside_the_band_is_a_single_attempt():
    assert ports_to_try(9000) == [9000]
    tried = []

    def bind(port):
        tried.append(port)
        raise _busy(port)

    server, port, skipped = bind_loopback(ports_to_try(9000), bind)
    assert tried == [9000]
    assert server is None
    assert skipped == [9000]
    message = band_busy_message(skipped)
    assert "9000" in message
    assert "--port 8900" in message


def test_busy_port_inside_the_band_moves_to_the_next_free_one():
    requested = DEFAULT_PORT + 3
    order = ports_to_try(requested)
    assert order[0] == requested
    assert set(order) == set(range(DEFAULT_PORT, DEFAULT_PORT + PORT_SPAN))
    tried = []

    def bind(port):
        tried.append(port)
        if port == requested:
            return None
        return "ready"

    server, port, skipped = bind_loopback(order, bind)
    assert tried == [requested, DEFAULT_PORT]
    assert server == "ready"
    assert skipped == [requested]
    assert port == DEFAULT_PORT


def test_full_band_tells_the_person_how_to_pass_port():
    def bind(port):
        raise _busy(port)

    server, _port, skipped = bind_loopback(ports_to_try(None), bind)
    assert server is None
    assert skipped[0] == DEFAULT_PORT
    assert skipped[-1] == DEFAULT_PORT + PORT_SPAN - 1
    message = band_busy_message(skipped)
    assert f"{DEFAULT_PORT}-{DEFAULT_PORT + PORT_SPAN - 1}" in message
    assert "python server.py --port 8900" in message


def test_a_port_outside_the_allowed_range_is_rejected():
    with pytest.raises(ValueError):
        ports_to_try(80)
    with pytest.raises(ValueError):
        ports_to_try(70000)


def test_other_bind_errors_stop_startup():
    def bind(port):
        raise OSError("permission denied")

    with pytest.raises(OSError, match="permission denied"):
        bind_loopback([DEFAULT_PORT], bind)


def test_address_in_use_recognizes_windows_and_posix():
    windows = OSError()
    windows.winerror = 10048
    posix = OSError()
    posix.errno = errno.EADDRINUSE
    other = OSError()
    other.errno = errno.EACCES
    assert address_in_use(windows)
    assert address_in_use(posix)
    assert not address_in_use(other)


def test_cli_flags():
    args = parse_args(["--port", "8780", "--no-browser"])
    assert args.port == 8780
    assert args.no_browser is True
    assert parse_args([]).port is None
    assert parse_args([]).no_browser is False
