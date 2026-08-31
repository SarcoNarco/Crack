"""Explicit host-local runtime-bound operations console."""

from coordinator.demo import DemoDependencies
from coordinator.live_events import LiveRunManager
from coordinator.main import create_app
from coordinator.runtime_binding import RuntimeBinding


def runtime_dependencies() -> DemoDependencies:
    binding = RuntimeBinding()
    return DemoDependencies(
        health_check=lambda: binding.call_endpoint(
            "GET", "/health", "token-teacher-fixed"
        ),
        resetter=binding.reset,
        preflight_metadata=binding.preflight_metadata,
        source_reader=binding.read_source,
        endpoint_caller=binding.call_endpoint,
        verifier_resetter=binding.reset,
    )


def create_runtime_app():
    return create_app(LiveRunManager(dependencies_factory=runtime_dependencies))


app = create_runtime_app()


def main() -> None:
    """Serve only the fixed host-local runtime console."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
