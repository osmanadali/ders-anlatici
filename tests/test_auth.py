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


def test_keys_saved_live_and_local_only(monkeypatch, tmp_path):
    from app import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("# Gemini\nGEMINI_API_KEY=\nDATA_DIR=veri\n", "utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = TestClient(main.app)
    r = c.post("/api/keys", json={"gemini": "AIzaTEST1234567890abcd"})
    assert r.status_code == 200 and r.json()["gemini"].startswith("AIza…")
    assert "1234567890" not in r.text  # anahtarın tamamı geri gönderilmez
    env = (tmp_path / ".env").read_text("utf-8")
    assert "GEMINI_API_KEY=AIzaTEST1234567890abcd" in env and "DATA_DIR=veri" in env and env.count("GEMINI_API_KEY") == 1
    assert config.gemini_key() == "AIzaTEST1234567890abcd"
    # uzaktan (telefon/tünel) anahtar girilemez
    monkeypatch.setenv("ERISIM_SIFRESI", "x")
    assert c.post("/api/keys", json={"gemini": "y"}, headers={"x-forwarded-for": "1.2.3.4"}).status_code in (401, 403)
