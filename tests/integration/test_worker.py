from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import duckdb
import httpx

DEMO_CSV = b"id,name,value\n1,  alpha  ,10\n2,beta,junk\n,gamma,30\n"

VENDOR_A_CSV = (
    b"TS,vertical,impressions\n2026-01-15 12:00:00,Auto,\n2026-05-24 09:30:00,RETAIL,500\n"
)


def _csv(name: str, body: bytes) -> dict:
    return {"file": (name, body, "text/csv")}


async def _silver_object_bytes(s3_endpoint: str, bucket: str, key: str) -> bytes | None:
    import aiobotocore.session
    from botocore.exceptions import ClientError

    session = aiobotocore.session.get_session()
    async with session.create_client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="minio",
        aws_secret_access_key="minio12345",
        region_name="us-east-1",
    ) as client:
        try:
            response = await client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise
        async with response["Body"] as stream:
            return await stream.read()  # type: ignore[no-any-return]


async def test_upload_triggers_worker_to_clean_demo(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[[], Coroutine[Any, Any, None]],
    s3_endpoint_url: str,
) -> None:
    upload = await client.post("/upload", files=_csv("demo.csv", DEMO_CSV), data={"source": "demo"})
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["file"]["id"]

    await run_worker_burst()

    status = await client.get(f"/status/{file_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "cleaned", body
    assert body["error_message"] is None


async def test_silver_parquet_readable_via_duckdb(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[[], Coroutine[Any, Any, None]],
    s3_endpoint_url: str,
    tmp_path: Any,
) -> None:
    upload = await client.post("/upload", files=_csv("demo.csv", DEMO_CSV), data={"source": "demo"})
    file_id = upload.json()["file"]["id"]
    created_at = upload.json()["file"]["created_at"]

    await run_worker_burst()

    year, month, day = created_at[:10].split("-")
    key = f"demo/{year}/{month}/{day}/{file_id}.parquet"
    body = await _silver_object_bytes(s3_endpoint_url, "silver", key)
    assert body is not None, f"no object at silver/{key}"

    parquet_path = tmp_path / "out.parquet"
    parquet_path.write_bytes(body)

    rows = duckdb.execute(f"SELECT * FROM read_parquet('{parquet_path}') ORDER BY id").fetchall()
    assert len(rows) == 2  # id=null row dropped
    ids = [r[0] for r in rows]
    names = [r[1] for r in rows]
    values = [r[2] for r in rows]
    assert ids == [1, 2]
    assert names == ["alpha", "beta"]
    assert values == [10, None]


async def test_missing_plan_marks_file_failed_permanently(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    upload = await client.post(
        "/upload", files=_csv("x.csv", DEMO_CSV), data={"source": "unknown_src"}
    )
    file_id = upload.json()["file"]["id"]

    await run_worker_burst()

    status = await client.get(f"/status/{file_id}")
    body = status.json()
    assert body["status"] == "failed"
    assert body["error_message"] is not None
    assert "no cached plan" in body["error_message"].lower()


async def test_invalid_csv_marks_file_failed_permanently(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    # File has source 'demo' (plan exists) but body lacks required 'value' column.
    bad_csv = b"unrelated,columns\nfoo,bar\n"
    upload = await client.post("/upload", files=_csv("bad.csv", bad_csv), data={"source": "demo"})
    file_id = upload.json()["file"]["id"]

    await run_worker_burst()

    status = await client.get(f"/status/{file_id}")
    body = status.json()
    assert body["status"] == "failed"
    assert body["error_message"] is not None


async def test_reprocess_is_idempotent(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    upload = await client.post("/upload", files=_csv("demo.csv", DEMO_CSV), data={"source": "demo"})
    file_id = upload.json()["file"]["id"]
    await run_worker_burst()

    first = await client.get(f"/status/{file_id}")
    assert first.json()["status"] == "cleaned"

    re = await client.post(f"/reprocess/{file_id}")
    assert re.status_code == 200
    assert re.json()["status"] == "received"

    await run_worker_burst()

    final = await client.get(f"/status/{file_id}")
    assert final.json()["status"] == "cleaned"


async def test_reprocess_returns_404_for_unknown_file(client: httpx.AsyncClient) -> None:
    response = await client.post("/reprocess/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_vendor_a_plan_applies(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[[], Coroutine[Any, Any, None]],
    s3_endpoint_url: str,
    tmp_path: Any,
) -> None:
    upload = await client.post(
        "/upload", files=_csv("v.csv", VENDOR_A_CSV), data={"source": "vendor_a"}
    )
    file_id = upload.json()["file"]["id"]
    created_at = upload.json()["file"]["created_at"]

    await run_worker_burst()

    final = await client.get(f"/status/{file_id}")
    assert final.json()["status"] == "cleaned"

    year, month, day = created_at[:10].split("-")
    key = f"vendor_a/{year}/{month}/{day}/{file_id}.parquet"
    body = await _silver_object_bytes(s3_endpoint_url, "silver", key)
    assert body is not None

    parquet_path = tmp_path / "v.parquet"
    parquet_path.write_bytes(body)
    rows = duckdb.execute(
        f"SELECT vertical, impressions FROM read_parquet('{parquet_path}') ORDER BY vertical"
    ).fetchall()
    assert rows == [("auto", 0), ("retail", 500)]
