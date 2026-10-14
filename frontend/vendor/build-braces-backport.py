"""Rebuild the reviewed braces nesting-depth backport from the published npm tarball."""

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
    "yQbXgO/OSZVD2IsiLlro+7Hf6Q18EJrKSEsdoMzKePKXct3gvD8oLcOQdIzGupr5Fj+EDe8gO/lxc1BzfMpxvA=="
)
OUTPUT_SHA256 = "915f19c374268cfb3f1575850d231119586670e276fdc5f73475ffaa8d9808a4"
VENDOR = Path(__file__).resolve().parent


def main() -> None:
    archive = Path(sys.argv[1])
    actual = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    if actual != UPSTREAM_SHA512:
        raise ValueError("published braces 3.0.3 tarball integrity mismatch")
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
                str(VENDOR / "braces-CVE-2026-93687.patch"),
            ],
            cwd=package,
            check=True,
        )
        metadata = json.loads((package / "package.json").read_text())
        metadata["version"] = "3.0.4-philly.1"
        metadata["private"] = True
        metadata["description"] = (
            "Temporary local braces 3.0.3 backport of CVE-2026-93687; not an upstream release."
        )
        for key in ["scripts", "devDependencies"]:
            metadata.pop(key, None)
        metadata["files"] = ["index.js", "lib/*.js", "LICENSE"]
        files = {
            str(path.relative_to(package)): path.read_bytes() for path in package.glob("lib/*.js")
        }
        files["index.js"] = (package / "index.js").read_bytes()
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
        (VENDOR / "braces-3.0.4-philly.1.tgz").write_bytes(result)


if __name__ == "__main__":
    main()
