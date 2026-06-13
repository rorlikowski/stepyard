import os

from stepyard.sdk.node import node


@node(name="file.read")
def file_read(path: str, encoding: str = "utf-8") -> str:
    """Reads and returns the contents of a file.

    Args:
        path: The file path.
        encoding: File encoding (default: utf-8).

    Outputs:
        Returns the entire file content as a string.
    """
    with open(path, encoding=encoding) as f:
        return f.read()


@node(name="file.write")
def file_write(path: str, content: str, encoding: str = "utf-8") -> str:
    """Writes content to a file and returns the path.

    Args:
        path: The file path.
        content: The string content to write.
        encoding: File encoding (default: utf-8).

    Outputs:
        Returns the absolute path of the saved file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        f.write(content)
    return os.path.abspath(path)


@node(name="file.list")
def file_list(path: str) -> list[str]:
    """Lists files and directories inside the given path.

    Args:
        path: The directory path.

    Outputs:
        Returns a list (array) of filenames/directory names.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Path '{path}' does not exist.")
    return os.listdir(path)


__all__ = ["file_list", "file_read", "file_write"]
