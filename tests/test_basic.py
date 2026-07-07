"""Basic import tests to verify setup."""


def test_imports():
    """Test that the application package imports cleanly."""
    import app.main

    assert app.main.app is not None
