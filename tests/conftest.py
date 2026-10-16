import os
import gc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()
    app.quit()
    gc.collect()


@pytest.fixture(autouse=True)
def cleanup_qt_widgets(qapp):
    yield
    for widget in list(qapp.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    qapp.processEvents()
    gc.collect()


@pytest.fixture
def mailbox_routes(request, monkeypatch):
    """Give unit-test habitats real signed routes to an unavailable local service."""
    from keri import kering

    def configure(hby):
        if 'real_routes' in request.keywords:
            return
        make_hab = hby.makeHab

        def make(*args, **kwargs):
            hab = make_hab(*args, **kwargs)
            hby.psr.parse(ims=bytearray(hab.makeLocScheme(
                url='http://127.0.0.1:1', scheme=kering.Schemes.http)))
            hby.psr.parse(ims=bytearray(hab.makeEndRole(
                eid=hab.pre, role=kering.Roles.mailbox)))
            return hab

        monkeypatch.setattr(hby, 'makeHab', make)
    return configure


def pytest_configure(config):
    config.addinivalue_line('markers', 'real_routes: use real IPEX route checks')
