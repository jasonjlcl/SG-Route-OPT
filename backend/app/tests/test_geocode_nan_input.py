from io import BytesIO

import pandas as pd

from app.services.validation import validate_rows


def test_validate_rows_treats_nan_like_text_as_missing():
    df = pd.DataFrame(
        [
            {
                "stop_ref": "S1",
                "address": "10 Bayfront Avenue",
                "postal_code": float("nan"),
                "tw_start": float("nan"),
                "tw_end": float("nan"),
                "phone": float("nan"),
                "contact_name": "<NA>",
            }
        ]
    )

    result = validate_rows(df)
    assert result.invalid_rows_count == 0
    assert result.valid_rows_count == 1

    row = result.valid_rows[0]
    assert row["postal_code"] is None
    assert row["tw_start"] is None
    assert row["tw_end"] is None
    assert row["phone"] is None
    assert row["contact_name"] is None


def test_geocode_uses_address_when_postal_code_is_missing(client, monkeypatch):
    queries: list[str] = []

    class DummyClient:
        def search(self, query: str):
            queries.append(query)
            lat = 1.30 + len(queries) * 0.001
            lon = 103.80 + len(queries) * 0.001
            return {
                "results": [
                    {
                        "LATITUDE": str(lat),
                        "LONGITUDE": str(lon),
                        "ADDRESS": f"Resolved {query}",
                        "POSTAL": "123456",
                    }
                ]
            }

    monkeypatch.setattr("app.services.geocoding.get_onemap_client", lambda: DummyClient())

    csv_content = """stop_ref,address,postal_code,demand,service_time_min
S1,10 Bayfront Avenue,,1,5
S2,1 Raffles Place,,1,5
"""

    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert upload.status_code == 200
    dataset_id = upload.json()["dataset_id"]

    geocode = client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})
    assert geocode.status_code == 200
    assert geocode.json()["success_count"] == 2

    assert queries == ["10 Bayfront Avenue", "1 Raffles Place"]
