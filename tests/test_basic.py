"""Basic import tests to verify setup."""
import sys


def test_imports():
    """Test that all modules can be imported."""
    try:
        print("All imports successful!")
        return True
    except Exception as e:
        print(f"Import error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
