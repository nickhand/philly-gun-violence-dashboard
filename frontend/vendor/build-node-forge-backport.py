"""Rebuild the reviewed Node-only Forge backport from the published npm tarball."""

import base64
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

UPSTREAM_SHA512 = (
    "LarFH0+6VfriEhqMMcLX2F7SwSXeWwnEAJEsYm5QKWchiVYVvJyV9v7UDvUv+w5HO23ZpQTXDv/GxdDdMyOuoQ=="
)
OUTPUT_SHA256 = "ea17a195ef66d4b10c9fb3093c26516d40be0da7d14b53ca6a842bc31e2b1ccc"
VENDOR = Path(__file__).resolve().parent


def main() -> None:
    archive = Path(sys.argv[1])
    actual = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    if actual != UPSTREAM_SHA512:
        raise ValueError("published node-forge 1.4.0 tarball integrity mismatch")
    with tempfile.TemporaryDirectory() as directory:
        with tarfile.open(archive) as source:
            source.extractall(directory, filter="data")
        package = Path(directory) / "package"
        subprocess.run(
            [
                "patch",
                "--batch",
                "--fuzz=0",
                "-p1",
                "-i",
                str(VENDOR / "node-forge-CVE-2026-85393.patch"),
            ],
            cwd=package,
            check=True,
        )
        metadata = json.loads((package / "package.json").read_text())
        metadata["version"] = "1.4.1-philly.1"
        metadata["private"] = True
        metadata["description"] = (
            "Temporary local node-forge 1.4.0 backport of CVE-2026-85393; not an upstream release."
        )
        for key in ["scripts", "devDependencies", "nyc", "jspm"]:
            metadata.pop(key, None)
        metadata["files"] = ["lib/*.js", "LICENSE"]
        files = {
            str(path.relative_to(package)): path.read_bytes() for path in package.glob("lib/*.js")
        }
        files["LICENSE"] = (package / "LICENSE").read_bytes()
        files["package.json"] = (json.dumps(metadata, indent=2) + "\n").encode()
        output = io.BytesIO()
        with (
            gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped,
            tarfile.open(fileobj=zipped, mode="w") as target,
        ):
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo("package/" + name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                target.addfile(info, io.BytesIO(data))
        result = output.getvalue()
        if hashlib.sha256(result).hexdigest() != OUTPUT_SHA256:
            raise ValueError("backport output differs from the reviewed artifact")
        (VENDOR / "node-forge-1.4.1-philly.1.tgz").write_bytes(result)


if __name__ == "__main__":
    main()
