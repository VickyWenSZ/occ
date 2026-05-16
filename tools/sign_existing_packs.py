"""
One-off: walk the live broker tree, sign every pack found, scp the .sig
back. Run from the OCC repo root after generating ~/.occ_publisher/signing.key
(any prior Hub deploy triggers this; or just `python -c "from node import crypto; crypto.load_or_generate_publisher_keypair()"`).

Threat addressed: existing packs were deployed before pack signing was wired
into the Hub. With strict mode default-ON in download_pack, those packs would
become uninstallable. This script back-fills the signatures so the cutover
doesn't break anything already shipped.

Idempotent: re-running re-signs (signature timestamp updates). Safe to run
multiple times if the broker tree changes mid-pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from node import crypto, pack_signing  # noqa: E402

BROKER_URL = "https://broker.opencognitivecommons.org"
SSH_TARGET = "root@116.203.61.136"
REMOTE_PACKS = "/opt/occ-packs"
_SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
_SCP = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]


def walk_packs(prefix: str = "") -> list[str]:
    """Depth-first walk of /tree[/path]. Returns the list of pack_paths
    (nodes where has_pack=True)."""
    found: list[str] = []
    with httpx.Client(timeout=15) as client:
        def recurse(path: str):
            url = f"{BROKER_URL}/tree" if not path else f"{BROKER_URL}/tree/{path}"
            r = client.get(url)
            if r.status_code != 200:
                return
            data = r.json()
            if isinstance(data, list):
                # Root: just names, no has_pack info — recurse into each
                for name in data:
                    recurse(name)
                return
            children = data.get("children", []) or []
            has_pack = bool(data.get("has_pack"))
            if has_pack:
                found.append(path)
            for child in children:
                child_path = f"{path}/{child}" if path else child
                recurse(child_path)
        recurse(prefix)
    return found


def fetch_pack_to_temp(pack_path: str, dest: Path) -> dict:
    """Download manifest.yaml + index.md + every page listed in the index.
    Returns {'manifest': bytes, 'pages': {rel: bytes}}. Lays them out in
    `dest` mirroring the on-broker structure so sign_pack() can hash them
    from disk."""
    dest.mkdir(parents=True, exist_ok=True)
    wiki = dest / "wiki"
    wiki.mkdir(exist_ok=True)
    with httpx.Client(timeout=30) as client:
        mr = client.get(f"{BROKER_URL}/packs/{pack_path}/manifest.yaml")
        mr.raise_for_status()
        (dest / "manifest.yaml").write_bytes(mr.content)

        ir = client.get(f"{BROKER_URL}/packs/{pack_path}/wiki/index.md")
        ir.raise_for_status()
        (wiki / "index.md").write_bytes(ir.content)

        # Parse table for page list
        import re as _re
        pages = []
        for line in ir.text.splitlines():
            m = _re.match(r"^\|\s*([^|]+?)\s*\|", line)
            if not m:
                continue
            rel = m.group(1).strip()
            if rel.lower() == "file" or rel.startswith("-") or not rel:
                continue
            pages.append(rel)

        for rel in pages:
            pr = client.get(f"{BROKER_URL}/packs/{pack_path}/wiki/{rel}")
            if pr.status_code != 200:
                print(f"    ! page fetch failed: {rel} (HTTP {pr.status_code})")
                continue
            out = wiki / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(pr.content)
    return {"pages_fetched": len(pages)}


def scp_sig(local_sig: Path, pack_path: str) -> bool:
    remote_dest = f"{SSH_TARGET}:{REMOTE_PACKS}/{pack_path}/manifest.sig"
    r = subprocess.run(
        _SCP + [str(local_sig.resolve()), remote_dest],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"    ! scp failed: {(r.stderr or r.stdout).strip()}")
        return False
    return True


def trigger_reindex():
    """Refresh the broker FTS5 index so /search picks up any pack whose
    body changed (it shouldn't have, but cheap insurance)."""
    from node import paths
    token_file = paths.reindex_token_file()
    if not token_file.exists():
        print(f"[reindex] no {token_file} — skipping")
        return
    token = token_file.read_text().strip()
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{BROKER_URL}/admin/reindex",
                json={},
                headers={"X-OCC-Token": token},
            )
        print(f"[reindex] HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"[reindex] failed: {e}")


def main():
    priv_b64, pub_b64 = crypto.load_or_generate_publisher_keypair()
    fp = pack_signing.fingerprint(pub_b64)
    print(f"Publisher fingerprint: {fp}")
    print(f"Discovering packs on {BROKER_URL} ...")
    packs = walk_packs()
    print(f"Found {len(packs)} packs: {packs}")
    if not packs:
        print("No packs to sign.")
        return

    with tempfile.TemporaryDirectory(prefix="occ-sign-") as tmp:
        tmp_root = Path(tmp)
        for i, pack_path in enumerate(packs, 1):
            print(f"\n[{i}/{len(packs)}] {pack_path}")
            pack_local = tmp_root / pack_path.replace("/", "__")
            try:
                info = fetch_pack_to_temp(pack_path, pack_local)
                print(f"    fetched {info['pages_fetched']} pages")
            except Exception as e:
                print(f"    ! fetch failed: {e}")
                continue
            try:
                sig = pack_signing.sign_pack(pack_local, priv_b64, signer_name=fp)
            except Exception as e:
                print(f"    ! sign failed: {e}")
                continue
            sig_local = pack_local / "manifest.sig"
            sig_local.write_text(json.dumps(sig, indent=2), encoding="utf-8")
            print(f"    signed: {len(sig['pages'])} pages, manifest_sha256={sig['manifest_sha256'][:12]}...")
            ok = scp_sig(sig_local, pack_path)
            print(f"    scp: {'OK' if ok else 'FAIL'}")

    trigger_reindex()
    print("\nDone.")


if __name__ == "__main__":
    main()
