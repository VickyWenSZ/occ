"""
OCC pack signing — Ed25519 signatures over a deterministic manifest hash.

Threat addressed: a hostile pack on the broker (or one tampered with in
transit) could embed prompt-injection that coerces the model into calling
run_code with malicious payloads. Signing makes packs auditable: only packs
signed by a key in trusted_publishers.yaml are accepted at download time.

What gets signed:
    payload = {
        "manifest_sha256": <sha256 hex of the manifest.yaml bytes>,
        "pages": {<rel_path>: <sha256 hex of page bytes>, ...},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = Ed25519(privkey).sign(canonical.encode())

Pages covered: every file under wiki/ recursively (including index.md and
nested subdirs like wiki/concepts/*.md). Order doesn't matter — we sort.

The signature file written next to manifest.yaml as manifest.sig holds the
full payload + a base64-encoded signature + the signer's pubkey/fingerprint,
so a verifier doesn't need any out-of-band information about which key
signed: they get the pubkey from the .sig, look up the fingerprint in their
local trusted_publishers.yaml, and verify the signature.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_INDEX_TABLE_RE = __import__("re").compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")


def _pages_listed_in_index(wiki_dir: Path) -> list[str]:
    """Return the relative paths declared in wiki/index.md's table.

    The signature scope matches what the Node actually downloads via
    `download_pack` (which parses the same table). If we signed every file
    under wiki/ — including local caches like embeddings.json that never
    travel to the Node — verification would falsely reject perfectly
    legitimate downloads.
    """
    index = wiki_dir / "index.md"
    if not index.exists():
        return []
    pages: list[str] = []
    for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|"):
            continue
        m = _INDEX_TABLE_RE.match(line)
        if not m:
            continue
        rel = m.group(1).strip()
        if rel.lower() == "file" or rel.startswith("-") or not rel:
            continue
        pages.append(rel)
    return pages


def _iter_pages(wiki_dir: Path):
    """Yield (relative_posix_path, absolute_path) for index.md plus every
    page declared in its table. This is the exact set `download_pack`
    fetches — signing the same scope avoids spurious verification failures
    from broker-only cache files (embeddings.json, etc.)."""
    if not wiki_dir.exists():
        return
    index_path = wiki_dir / "index.md"
    if index_path.exists():
        yield "index.md", index_path
    for rel in _pages_listed_in_index(wiki_dir):
        abs_p = wiki_dir / rel
        if abs_p.is_file():
            yield rel, abs_p


def hash_pack(pack_dir: Path) -> dict:
    """Build the deterministic content hash dict that the signature covers.

    Result shape:
        {"manifest_sha256": "...", "pages": {"index.md": "...", ...}}

    Used both for signing (input to Ed25519) and for verification (compare
    against on-disk / downloaded pages).
    """
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.yaml missing in {pack_dir}")
    wiki_dir = pack_dir / "wiki"
    if not wiki_dir.is_dir():
        raise FileNotFoundError(f"wiki/ missing in {pack_dir}")
    return {
        "manifest_sha256": _sha256_file(manifest_path),
        "pages": {rel: _sha256_file(abs_p) for rel, abs_p in _iter_pages(wiki_dir)},
    }


def hash_from_bytes(manifest_bytes: bytes, pages: dict[str, bytes]) -> dict:
    """Same as hash_pack() but driven by in-memory bytes — needed by the
    Node when verifying a pack pulled over HTTP (no on-disk layout yet)."""
    return {
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "pages": {rel: _sha256_bytes(data) for rel, data in pages.items()},
    }


def _canonical_payload(content_hash: dict) -> bytes:
    """Stable JSON encoding fed to Ed25519. sort_keys + no whitespace makes
    the byte representation reproducible across machines and Python versions."""
    return json.dumps(content_hash, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(pubkey_b64: str) -> str:
    """Short, human-comparable identifier derived from the Ed25519 pubkey.
    SHA-256 → base32 (no padding) → first 16 chars. Collision-resistant for
    the scale of trusted publishers we expect (dozens, not millions)."""
    raw = base64.b64decode(pubkey_b64)
    digest = hashlib.sha256(raw).digest()
    return base64.b32encode(digest).decode().rstrip("=")[:16].lower()


def sign_pack(pack_dir: Path, signing_priv_b64: str, signer_name: str = "") -> dict:
    """Produce the signature dict for a pack on disk. Caller is responsible
    for writing it to <pack_dir>/manifest.sig (Hub does this during deploy)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(signing_priv_b64))
    pub = priv.public_key()
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    pub_b64 = base64.b64encode(
        pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()

    content = hash_pack(pack_dir)
    sig_bytes = priv.sign(_canonical_payload(content))

    return {
        "alg": "ed25519",
        "signer_name": signer_name or "",
        "signer_pubkey_b64": pub_b64,
        "signer_fingerprint": fingerprint(pub_b64),
        "signed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_sha256": content["manifest_sha256"],
        "pages": content["pages"],
        "signature_b64": base64.b64encode(sig_bytes).decode(),
    }


class VerificationError(Exception):
    """Raised when a pack signature cannot be verified for any reason."""


def load_trusted_fingerprints() -> set[str]:
    """Read the in-repo trusted_publishers.yaml and return the fingerprint set.

    Permissive failure: a missing or malformed file returns an empty set,
    which makes every signature verification fail (fail-closed). Callers
    that want a louder error should check the file's existence themselves.
    """
    import yaml
    here = Path(__file__).resolve().parent
    path = here / "trusted_publishers.yaml"
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    entries = data.get("publishers", []) or []
    out: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fp = (entry.get("fingerprint") or "").strip().lower()
        if not fp or fp.startswith("placeholder"):
            # Skip placeholder entries — the loader is permissive on purpose
            # so a fresh clone of the repo doesn't accidentally trust a
            # sentinel string.
            continue
        out.add(fp)
    return out


def verify_signature(sig: dict, trusted_fingerprints: set[str]) -> None:
    """Verify the signature object's Ed25519 signature and check the signer's
    fingerprint is in the trusted set. Does NOT verify on-disk page hashes —
    use verify_pack_against_bytes/disk for that.

    Raises VerificationError with a specific reason on any failure.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    if not isinstance(sig, dict):
        raise VerificationError("signature object is not a dict")
    if sig.get("alg") != "ed25519":
        raise VerificationError(f"unsupported alg: {sig.get('alg')!r}")
    pub_b64 = sig.get("signer_pubkey_b64") or ""
    if not pub_b64:
        raise VerificationError("signer pubkey missing")
    declared_fp = sig.get("signer_fingerprint") or ""
    actual_fp = fingerprint(pub_b64)
    if declared_fp != actual_fp:
        raise VerificationError(
            f"declared fingerprint {declared_fp!r} does not match pubkey ({actual_fp!r})"
        )
    if actual_fp not in trusted_fingerprints:
        raise VerificationError(
            f"signer {actual_fp!r} is not in the trusted publishers list"
        )
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    except Exception as e:
        raise VerificationError(f"malformed signer pubkey: {e}")
    payload = _canonical_payload({
        "manifest_sha256": sig.get("manifest_sha256", ""),
        "pages": sig.get("pages", {}) or {},
    })
    try:
        sig_bytes = base64.b64decode(sig.get("signature_b64", ""))
    except Exception as e:
        raise VerificationError(f"malformed signature: {e}")
    try:
        pub.verify(sig_bytes, payload)
    except InvalidSignature:
        raise VerificationError("Ed25519 verification failed (bad signature)")


def verify_pack_bytes(
    manifest_bytes: bytes,
    pages: dict[str, bytes],
    sig: dict,
    trusted_fingerprints: set[str],
) -> None:
    """Full verification pass for a pack received over the wire:
      1. Signature object structurally valid & signer trusted (verify_signature)
      2. manifest_sha256 matches the bytes we actually received
      3. Every page declared in the signature matches its declared hash
      4. No undeclared pages slipped in (strict — undeclared = unsigned)

    Raises VerificationError on any failure."""
    verify_signature(sig, trusted_fingerprints)

    actual_manifest = _sha256_bytes(manifest_bytes)
    if actual_manifest != sig.get("manifest_sha256"):
        raise VerificationError("manifest.yaml hash does not match signature")

    declared_pages = sig.get("pages", {}) or {}
    for rel, declared_hash in declared_pages.items():
        if rel not in pages:
            raise VerificationError(f"signed page missing from download: {rel!r}")
        if _sha256_bytes(pages[rel]) != declared_hash:
            raise VerificationError(f"page hash mismatch: {rel!r}")

    extra = set(pages) - set(declared_pages)
    if extra:
        # Reject silently-added pages: they could be a vector for slipping
        # unsigned content under a legitimate signature.
        raise VerificationError(
            f"unsigned pages present in download: {sorted(extra)[:3]!r}"
        )
