from __future__ import annotations

from pathlib import Path

import yaml

from backends import Backend, EchoBackend, RemoteBackend, VllmBackend


class BackendRegistry:
    def __init__(
        self, backends: dict[str, Backend], default_name: str, fallback_name: str | None = None
    ) -> None:
        self._backends = backends
        self._default_name = default_name
        self._fallback_name = fallback_name

    def get(self, name: str) -> Backend:
        """Return a backend by name or raise KeyError."""
        return self._backends[name]

    def get_default(self) -> Backend:
        """Return the default backend."""
        return self._backends[self._default_name]

    def get_fallback(self) -> Backend | None:
        """Return the fallback backend, or None if not configured."""
        if self._fallback_name:
            return self._backends.get(self._fallback_name)
        return None

    def list_backends(self) -> list[Backend]:
        """Return all registered backends."""
        return list(self._backends.values())

    @classmethod
    def from_config(cls, path: str | None = None) -> BackendRegistry:
        """Build a BackendRegistry from a YAML config file.

        If no config file is found, returns an echo-only registry.

        Args:
            path: Optional explicit path to a YAML config file.

        Returns:
            A fully constructed BackendRegistry.
        """
        config_path = Path(path) if path else Path("config.yaml")
        if not config_path.exists():
            return cls({"echo": EchoBackend("echo")}, "echo")

        raw = yaml.safe_load(config_path.read_text())
        default_name = raw.get("default_backend", "echo")
        backends: dict[str, Backend] = {}

        for name, entry in raw.get("backends", {}).items():
            backend_type = entry.get("type", name)
            if backend_type == "echo":
                backends[name] = EchoBackend(name)
            elif backend_type == "vllm":
                url = entry.get("url")
                if not url:
                    raise ValueError(
                        f"Backend '{name}' (type 'vllm') requires a 'url'"
                    )
                backends[name] = VllmBackend(name, url)
            else:
                url = entry.get("url")
                if not url:
                    raise ValueError(
                        f"Backend '{name}' (type '{backend_type}') requires a 'url'"
                    )
                backends[name] = RemoteBackend(name, url, type=backend_type)

        if default_name not in backends:
            raise ValueError(
                f"default_backend '{default_name}' not defined in backends"
            )

        fallback_name = raw.get("fallback_backend")
        if fallback_name and fallback_name not in backends:
            raise ValueError(
                f"fallback_backend '{fallback_name}' not defined in backends"
            )

        return cls(backends, default_name, fallback_name)
