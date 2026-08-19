"""Tests for fail-closed deployment configuration parsing."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

MODULE_PATH = Path(__file__).with_name("check_deployment_config.py")
SCOPE_PATH = Path(__file__).with_name("scope.py")


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deployment_config_checker", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load deployment configuration checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()


def _load_scope() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deployment_scope", SCOPE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load CI scope")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCOPE = _load_scope()


class DockerInputContracts(unittest.TestCase):
    def test_local_sources_are_extracted_from_shell_and_json_forms(self) -> None:
        source = """
        COPY --chown=app packages/api/app/ /app/api/app/
        COPY --chmod=0444 ["packages/api/README.md", "/app/api/README.md"]
        ADD . /app
        """
        self.assertEqual(
            CHECKER._local_docker_sources(source),
            ("packages/api/app/", "packages/api/README.md", "."),
        )
        self.assertEqual(
            CHECKER._local_docker_mappings(source),
            (
                ("packages/api/app/", "/app/api/app/"),
                ("packages/api/README.md", "/app/api/README.md"),
                (".", "/app"),
            ),
        )

    def test_remote_add_and_stage_copy_are_not_local_context_inputs(self) -> None:
        source = """
        ADD --checksum=sha256:abc https://example.test/archive.tgz /tmp/archive.tgz
        COPY --from=builder /app/bin /usr/local/bin/app
        """
        self.assertEqual(CHECKER._local_docker_sources(source), ())

    def test_malformed_or_ambiguous_copy_fails_closed(self) -> None:
        cases = (
            "COPY --chown app . /app",
            'COPY ["."]',
            "COPY \\",
        )
        for source in cases:
            with self.subTest(source=source), self.assertRaises(CHECKER.ConfigurationError):
                CHECKER._local_docker_sources(source)

    def test_only_literal_cache_run_mounts_are_allowed(self) -> None:
        self.assertEqual(
            CHECKER._local_docker_sources("RUN --mount=type=cache,target=/root/.cache true"),
            (),
        )
        for mount in (
            "--mount=source=packages/api/tests,target=/tmp/tests",
            "--mount=type=$MOUNT_TYPE,source=packages/api/tests,target=/tmp/tests",
            "--mount=type=secret,id=token",
        ):
            with (
                self.subTest(mount=mount),
                self.assertRaisesRegex(CHECKER.ConfigurationError, "only literal cache RUN mounts"),
            ):
                CHECKER._local_docker_sources(f"RUN {mount} true")

    def test_non_default_docker_escape_directive_is_rejected(self) -> None:
        source = """# escape=`
        COPY packages/api/app/ `
          /app/api/app/
        """
        with self.assertRaisesRegex(CHECKER.ConfigurationError, "escape directives"):
            CHECKER._local_docker_sources(source)

    def test_every_current_local_docker_input_selects_its_image_job(self) -> None:
        cases = (
            ("api", "packages/api/Dockerfile"),
            ("etl", "packages/etl/Dockerfile"),
        )
        for workflow, relative_path in cases:
            source = (CHECKER.REPOSITORY_ROOT / relative_path).read_text()
            for local_input in CHECKER._local_docker_sources(source):
                candidate = (
                    f"{local_input}ci-routing-probe.py"
                    if local_input.endswith("/")
                    else local_input
                )
                with self.subTest(workflow=workflow, local_input=local_input):
                    self.assertTrue(SCOPE.classify(workflow, [candidate])["image"])


if __name__ == "__main__":
    unittest.main()
