from io import BytesIO


def test_phone_is_normalized_to_e164(client):
    csv_content = """stop_ref,address,phone
S1,10 Bayfront Avenue,81234567
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert upload.status_code == 200
    dataset_id = upload.json()["dataset_id"]

    stops = client.get(f"/api/v1/datasets/{dataset_id}/stops")
    assert stops.status_code == 200
    body = stops.json()
    assert body["items"][0]["phone"] == "+6581234567"


def test_phone_validation_rejects_invalid_format(client):
    csv_content = """stop_ref,address,phone
S1,10 Bayfront Avenue,123
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "false"},
    )
    assert upload.status_code == 200
    summary = upload.json()["validation_summary"]
    assert summary["invalid_rows_count"] == 1
