from types import SimpleNamespace

from app.services import storage as storage_service


def test_signed_download_url_uses_iam_fallback_when_private_key_missing(monkeypatch):
    class FakeCredentials:
        service_account_email = "route-app-api-sa@example.iam.gserviceaccount.com"
        token = None

        def refresh(self, _request) -> None:
            self.token = "token-abc"

    class FakeBlob:
        def __init__(self) -> None:
            self.calls = []

        def generate_signed_url(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("private key unavailable")
            return "https://signed.example/download"

    fake_blob = FakeBlob()

    class FakeBucket:
        def blob(self, _name: str):
            return fake_blob

    class FakeClient:
        def __init__(self, project=None) -> None:
            self._credentials = FakeCredentials()

        def bucket(self, _bucket_name: str):
            return FakeBucket()

    monkeypatch.setattr(storage_service, "STORAGE_AVAILABLE", True)
    monkeypatch.setattr(storage_service, "_bucket_name", lambda: "route_app")
    monkeypatch.setattr(storage_service, "Request", lambda: object(), raising=False)
    monkeypatch.setattr(storage_service, "storage", SimpleNamespace(Client=FakeClient), raising=False)

    url = storage_service.signed_download_url(object_path="driver_packs/1/driver_pack.pdf")

    assert url == "https://signed.example/download"
    assert len(fake_blob.calls) == 2
    assert fake_blob.calls[1]["service_account_email"] == "route-app-api-sa@example.iam.gserviceaccount.com"
    assert fake_blob.calls[1]["access_token"] == "token-abc"
