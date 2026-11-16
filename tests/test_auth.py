from fastapi.testclient import TestClient

from app import auth, main


def test_local_free_remote_needs_password(monkeypatch):
    c = TestClient(main.app)
    assert c.get("/api/settings").status_code == 200  # yerel
    remote = {"x-forwarded-for": "1.2.3.4"}
    monkeypatch.delenv("ERISIM_SIFRESI", raising=False)
    monkeypatch.setattr(auth, "phone_info", lambda: {})
    assert c.get("/api/settings", headers=remote).status_code == 403
    monkeypatch.setenv("ERISIM_SIFRESI", "kalem42")
    assert c.get("/api/settings", headers=remote).status_code == 401
    assert c.get("/", headers=remote, follow_redirects=False).headers["location"] == "/giris"
    assert "Şifre yanlış" in c.post("/api/login", data={"sifre": "yanlis"}, headers=remote).text
    r = c.post("/api/login", data={"sifre": "kalem42"}, headers=remote, follow_redirects=False)
    assert r.status_code == 303
    c.cookies.set(auth.COOKIE, r.cookies[auth.COOKIE])
    assert c.get("/api/settings", headers=remote).status_code == 200
