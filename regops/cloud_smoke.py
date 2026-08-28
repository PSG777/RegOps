"""Non-Gemini smoke checks against a deployed RegOps API."""

import argparse
import json
from urllib.request import Request, urlopen


def request(base_url: str, path: str, method: str = "GET") -> dict:
    with urlopen(Request(base_url + path, method=method), timeout=20) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Backend Cloud Run URL")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    health = request(base_url, "/api/health")
    dashboard = request(base_url, "/api/demo/dashboard")
    denied = request(base_url, "/api/demo/runtime/unsafe-email", "POST")
    allowed = request(base_url, "/api/demo/runtime/refund", "POST")
    lineage = request(
        base_url, f"/api/demo/lineage/{denied['audit_event_id']}"
    )
    assert health["status"] == "ok" and health["infrastructure"]["environment"] == "cloud"
    assert dashboard["deployment"]["status"] == "ACTIVE"
    assert denied["decision"] == "DENY" and denied["tool_executed"] is False
    assert allowed["decision"] == "ALLOW" and allowed["tool_executed"] is True
    assert lineage["regulation"]["regulation_id"]
    print("Cloud smoke test passed: health, persistence projection, DENY, ALLOW, lineage.")


if __name__ == "__main__":
    main()
