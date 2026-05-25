from __future__ import annotations

import hashlib

import httpx
import pytest

SAMPLE_CSV = b"id,name,value\n1,alpha,10\n2,beta,20\n"
SAMPLE_SHA256 = hashlib.sha256(SAMPLE_CSV).hexdigest()


def _csv_files(name: str = "sample.csv", body: bytes = SAMPLE_CSV) -> dict:
    return {"file": (name, body, "text/csv")}


async def test_upload_happy_path(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/upload",
        files=_csv_files(),
        data={"source": "demo"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["duplicate"] is False
    assert payload["file"]["source"] == "demo"
    assert payload["file"]["sha256"] == SAMPLE_SHA256
    assert payload["file"]["byte_size"] == len(SAMPLE_CSV)
    assert payload["file"]["status"] == "received"
    assert payload["file"]["s3_uri"].startswith("s3://bronze/demo/")
    assert payload["file"]["s3_uri"].endswith(f"/{SAMPLE_SHA256}.csv")


async def test_upload_is_idempotent_on_source_plus_sha256(client: httpx.AsyncClient) -> None:
    first = await client.post("/upload", files=_csv_files(), data={"source": "demo"})
    second = await client.post("/upload", files=_csv_files(), data={"source": "demo"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["file"]["id"] == second.json()["file"]["id"]
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True


async def test_upload_different_source_creates_distinct_row(client: httpx.AsyncClient) -> None:
    a = await client.post("/upload", files=_csv_files(), data={"source": "vendor_a"})
    b = await client.post("/upload", files=_csv_files(), data={"source": "vendor_b"})

    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["file"]["id"] != b.json()["file"]["id"]


async def test_upload_rejects_bad_content_type(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/upload",
        files={"file": ("sample.png", b"\x89PNG", "image/png")},
        data={"source": "demo"},
    )
    assert response.status_code == 415


async def test_upload_rejects_malformed_source(client: httpx.AsyncClient) -> None:
    response = await client.post("/upload", files=_csv_files(), data={"source": "Bad-Source"})
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["source", "file"])
async def test_upload_rejects_missing_field(client: httpx.AsyncClient, missing: str) -> None:
    files = _csv_files() if missing != "file" else {}
    data = {} if missing == "source" else {"source": "demo"}
    response = await client.post("/upload", files=files, data=data)
    assert response.status_code == 422


async def test_get_status_returns_row(client: httpx.AsyncClient) -> None:
    upload = await client.post("/upload", files=_csv_files(), data={"source": "demo"})
    file_id = upload.json()["file"]["id"]

    status_response = await client.get(f"/status/{file_id}")
    assert status_response.status_code == 200
    assert status_response.json()["id"] == file_id


async def test_get_status_returns_404_for_unknown_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/status/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_list_files_pagination_and_ordering(client: httpx.AsyncClient) -> None:
    await client.post(
        "/upload",
        files=_csv_files("a.csv", b"id\n1\n"),
        data={"source": "demo"},
    )
    await client.post(
        "/upload",
        files=_csv_files("b.csv", b"id\n2\n"),
        data={"source": "demo"},
    )

    page = await client.get("/files", params={"limit": 1, "offset": 0})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    newest_name = body["items"][0]["original_name"]

    next_page = await client.get("/files", params={"limit": 1, "offset": 1})
    assert next_page.json()["items"][0]["original_name"] != newest_name


async def test_list_files_filters_by_source(client: httpx.AsyncClient) -> None:
    await client.post(
        "/upload",
        files=_csv_files("a.csv", b"id\n1\n"),
        data={"source": "vendor_a"},
    )
    await client.post(
        "/upload",
        files=_csv_files("b.csv", b"id\n2\n"),
        data={"source": "vendor_b"},
    )

    response = await client.get("/files", params={"source": "vendor_a"})
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "vendor_a"


async def test_list_files_rejects_bad_pagination(client: httpx.AsyncClient) -> None:
    response = await client.get("/files", params={"limit": 0})
    assert response.status_code == 422


async def test_metrics_endpoint_exposes_upload_counter(client: httpx.AsyncClient) -> None:
    await client.post("/upload", files=_csv_files(), data={"source": "demo"})
    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    assert 'signal_uploads_total{result="created",source="demo"}' in body
