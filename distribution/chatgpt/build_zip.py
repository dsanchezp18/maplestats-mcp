"""Build the ZIP that OpenAI's plugin portal takes for the ChatGPT app directory.

The ZIP holds plugin.json and mcp.json at its root and the logo under assets/.
The version is the package's own (maplestats_mcp.__version__), so plugin.json
in the repo carries none, and the demo video link is given at build time, since
the recording is made after the code:

    uv run python distribution/chatgpt/build_zip.py --demo-url https://youtu.be/...

The ZIP is written to build/chatgpt/ (gitignored). Without --demo-url it is
still built, with a warning: the portal refuses a submission without one.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from maplestats_mcp import __version__

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
LOGO = ROOT / "site" / "assets" / "icon-512.png"
OUT_DIR = ROOT / "build" / "chatgpt"


def plugin_manifest(demo_url: str) -> dict:
    manifest = json.loads((HERE / "plugin.json").read_text(encoding="utf-8"))
    manifest["version"] = __version__
    manifest["extensions"]["com.openai"]["review"]["demo_recording_url"] = demo_url
    return manifest


def build(demo_url: str, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"maplestats-chatgpt-{__version__}.zip"
    manifest = json.dumps(plugin_manifest(demo_url), ensure_ascii=False, indent=2) + "\n"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", manifest)
        archive.write(HERE / "mcp.json", "mcp.json")
        archive.write(LOGO, "assets/logo.png")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-url", default="", help="reviewer-accessible demo video URL")
    args = parser.parse_args()
    if not args.demo_url.startswith("https://"):
        print("warning: no https --demo-url; the portal needs one to submit", file=sys.stderr)
    print(build(args.demo_url))
