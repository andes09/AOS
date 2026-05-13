from src.config import Settings


def test_allowed_origins_local():
    s = Settings(environment="local", frontend_url="http://localhost:5174")
    assert "http://localhost:5174" in s.allowed_origins
    assert "http://localhost:5173" in s.allowed_origins  # auto-added


def test_allowed_origins_production():
    s = Settings(
        environment="production",
        frontend_url="https://omada.up.railway.app",
    )
    assert "https://omada.up.railway.app" in s.allowed_origins
    assert "http://localhost:5173" not in s.allowed_origins


def test_multiple_origins_parsed():
    s = Settings(
        environment="production",
        frontend_url="https://a.railway.app,https://b.railway.app",
    )
    assert len(s.allowed_origins) == 2
    assert "https://a.railway.app" in s.allowed_origins
    assert "https://b.railway.app" in s.allowed_origins
