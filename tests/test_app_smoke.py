from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_exception() -> None:
    app = AppTest.from_file("app.py")
    app.run(timeout=30)
    assert not app.exception
    assert any(element.value == "Tender setup" for element in app.subheader)
    assert len(app.sidebar.radio) == 1

    app.sidebar.radio[0].set_value("Review Bidders")
    app.run(timeout=60)
    assert not app.exception
    assert any(element.value == "Review bidders" for element in app.subheader)
