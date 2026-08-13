import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def test_supplied_har_confirms_execute_chain():
    path = Path(__file__).resolve().parents[1] / "aaaa.har"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = data["log"]["entries"]
    execute_code = [e for e in entries if urlparse(e["request"]["url"]).path.endswith("/api/computation-api/executeCode")]
    execute_dag = [e for e in entries if urlparse(e["request"]["url"]).path.endswith("/api/computation-api/executeDag")]
    assert len(execute_code) >= 1
    ec = execute_code[-1]
    assert ec["request"]["method"] == "POST"
    assert ec["response"]["status"] == 200
    req = json.loads(ec["request"]["postData"]["text"])
    resp = json.loads(ec["response"]["content"]["text"])
    assert "code" in req and req["code"].strip()
    assert isinstance(resp.get("dags"), dict) and len(resp["dags"]) == 3
    expected = set(resp["dags"].values())
    got = set()
    for e in execute_dag:
        q = parse_qs(urlparse(e["request"]["url"]).query)
        dag_id = (q.get("dagId") or [""])[0]
        payload = json.loads(e["response"]["content"]["text"])
        if e["response"]["status"] == 200 and payload.get("status") == "success":
            got.add(dag_id)
    assert expected <= got
