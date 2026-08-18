from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_compose_shares_the_demo_apps_fixed_loopback_namespace() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    coordinator = services["coordinator"]
    demo_app = services["app-under-test"]

    assert coordinator["network_mode"] == "service:app-under-test"
    assert "ports" not in coordinator
    assert "app-under-test" in coordinator["depends_on"]
    assert set(demo_app["ports"]) == {
        "127.0.0.1:8000:8000",
        "127.0.0.1:8100:8100",
    }
