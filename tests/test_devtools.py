import asyncio

from trxstation.devtools.loop_noise import install_quiet_reset_handler


def test_quiet_handler_ignores_connection_resets_but_reports_other_errors():
    loop = asyncio.new_event_loop()
    try:
        reported = []
        loop.set_exception_handler(lambda lp, ctx: reported.append(ctx["exception"]))
        handler = install_quiet_reset_handler(loop)
        handler(loop, {"exception": ConnectionResetError("10054")})
        handler(loop, {"exception": BrokenPipeError()})
        assert reported == []
        boom = RuntimeError("vrai problème")
        handler(loop, {"exception": boom})
        assert reported == [boom]
    finally:
        loop.close()


def test_aiortc_close_race_is_recognised_precisely(tmp_path):
    """Seule l'InvalidStateError levée dans close() de rtcpeerconnection.py est ignorée."""
    import importlib.util

    from trxstation.asyncio_noise import is_aiortc_close_race

    counter = []

    def raised_from(filename, function):
        counter.append(1)
        folder = tmp_path / f"c{len(counter)}"                       # un dossier par essai : pas de cache .pyc périmé
        folder.mkdir()
        path = folder / filename
        path.write_text(f"import asyncio\n\nasync def {function}():\n    raise asyncio.InvalidStateError('invalid state')\n")
        spec = importlib.util.spec_from_file_location(filename[:-3], path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            asyncio.run(getattr(module, function)())
        except asyncio.InvalidStateError as exc:
            return exc

    assert is_aiortc_close_race(raised_from("rtcpeerconnection.py", "close"))
    assert not is_aiortc_close_race(raised_from("rtcpeerconnection.py", "autre"))      # autre fonction
    assert not is_aiortc_close_race(raised_from("ailleurs.py", "close"))               # autre fichier
    assert not is_aiortc_close_race(RuntimeError("x")) and not is_aiortc_close_race(None)


def test_quiet_handler_also_ignores_the_aiortc_race_but_reports_everything_else(tmp_path):
    from trxstation.asyncio_noise import install_quiet_handler
    loop = asyncio.new_event_loop()
    try:
        reported = []
        loop.set_exception_handler(lambda lp, ctx: reported.append(ctx["exception"]))
        handler = install_quiet_handler(loop)
        handler(loop, {"exception": asyncio.InvalidStateError("ailleurs")})            # pas la course connue : signalée
        assert len(reported) == 1
    finally:
        loop.close()
