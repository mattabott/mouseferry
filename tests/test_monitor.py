from tests.conftest import mouseferry


def test_module_imports():
    assert hasattr(mouseferry, "MouseFerry")
