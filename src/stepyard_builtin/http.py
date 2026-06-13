import json
import urllib.parse
import urllib.request
from typing import Any

from stepyard.sdk.node import node


@node(name="http.request")
def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Performs an HTTP request and returns structured response details.

    Args:
        url: The target URL.
        method: HTTP method, e.g., GET, POST (default: GET).
        headers: HTTP headers.
        data: Form data to send (application/x-www-form-urlencoded).
        json_body: JSON payload to send (application/json).

    Outputs:
        status: HTTP status code.
        headers: Response headers.
        body: Response body (parsed as a JSON dictionary if possible, otherwise text).
        error: Error message if the request failed.
    """
    req_headers = headers or {}
    req_data = None

    if json_body is not None:
        req_data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif data is not None:
        req_data = urllib.parse.urlencode(data).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http and https schemes are allowed.")

    req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method.upper())

    try:
        with urllib.request.urlopen(req) as response:  # nosec B310
            res_body = response.read()
            status = response.status
            try:
                res_data = json.loads(res_body.decode("utf-8"))
            except Exception:
                res_data = res_body.decode("utf-8", errors="replace")

            return {
                "status": status,
                "headers": dict(response.headers),
                "body": res_data,
            }
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_json = json.loads(err_body)
        except Exception:
            err_json = err_body if "err_body" in locals() else str(e)

        return {
            "status": e.code,
            "headers": dict(e.headers),
            "body": err_json,
            "error": str(e),
        }


@node(name="http.download")
def http_download(url: str, dest: str) -> str:
    """Downloads a file from url to dest path.

    Args:
        url: The URL to download.
        dest: The absolute or relative local destination path.

    Outputs:
        Returns the absolute path of the downloaded file.
    """
    import os

    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http and https schemes are allowed.")

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    urllib.request.urlretrieve(url, dest)  # nosec B310
    return os.path.abspath(dest)


__all__ = ["http_download", "http_request"]
