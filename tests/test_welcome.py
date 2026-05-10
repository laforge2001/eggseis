"""WelcomeWidget — empty-state shown when no project is loaded."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def welcome(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from eggseis.widgets.welcome import WelcomeWidget

    w = WelcomeWidget()
    qtbot.addWidget(w)
    return w


def test_open_button_emits_signal(welcome, qtbot):
    received = []
    welcome.openProjectRequested.connect(lambda: received.append(True))
    welcome._open_button.click()
    assert received == [True]


def test_new_button_emits_signal(welcome, qtbot):
    received = []
    welcome.newProjectRequested.connect(lambda: received.append(True))
    welcome._new_button.click()
    assert received == [True]


def test_recent_list_populated_from_recent_file(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from eggseis.recent import add_recent
    from eggseis.widgets.welcome import WelcomeWidget

    add_recent("/path/to/project_a")
    add_recent("/path/to/project_b")

    w = WelcomeWidget()
    qtbot.addWidget(w)
    items = [w._recent_list.item(i).text() for i in range(w._recent_list.count())]
    assert any("project_b" in t for t in items)


def test_recent_click_emits_path(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from eggseis.recent import add_recent
    from eggseis.widgets.welcome import WelcomeWidget

    add_recent("/abs/some_project")
    w = WelcomeWidget()
    qtbot.addWidget(w)

    received = []
    w.recentRequested.connect(received.append)
    w._recent_list.itemClicked.emit(w._recent_list.item(0))
    assert received == ["/abs/some_project"]
