from server.http_security import transport_security_settings


def test_transport_security_adds_configured_tunnel_hosts_and_origins():
    hostname = "able-attributes-suggesting-usr.trycloudflare.com"

    settings = transport_security_settings(f" {hostname},, {hostname} ")

    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == [
        "127.0.0.1:*",
        "localhost:*",
        hostname,
        f"{hostname}:*",
    ]
    assert settings.allowed_origins == [
        "http://127.0.0.1:*",
        "http://localhost:*",
        f"https://{hostname}",
        f"https://{hostname}:*",
    ]
