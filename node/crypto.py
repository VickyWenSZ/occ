from pathlib import Path
import base64, os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256

from node import paths


def _restrict_perms(path: Path, mode: int) -> None:
    """Best-effort chmod. POSIX honours it; Windows ignores most bits but the
    call itself is harmless. Swallow failures so a read-only mount or odd FS
    doesn't break key load."""
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def load_or_generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes). Generates and persists if not found."""
    priv_file = paths.x25519_private_key()
    pub_file = paths.x25519_public_key()

    if priv_file.exists() and pub_file.exists():
        # Re-assert tight perms on every load — covers the case where the
        # files were created by an older version that left them world-readable.
        _restrict_perms(priv_file, 0o600)
        _restrict_perms(pub_file, 0o644)
        return priv_file.read_bytes(), pub_file.read_bytes()

    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    priv_file.write_bytes(priv_bytes)
    _restrict_perms(priv_file, 0o600)
    pub_file.write_bytes(pub_bytes)
    _restrict_perms(pub_file, 0o644)
    return priv_bytes, pub_bytes


def _derive_aes_key(shared_secret: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=b"occ-v2").derive(shared_secret)


def encrypt(payload: bytes, recipient_pubkey_b64: str, aad: bytes = b"") -> str:
    """Encrypt payload for recipient. Returns base64-encoded ciphertext.

    `aad` is bound into the AES-GCM tag without being included in the
    ciphertext. The Critic side must pass the identical bytes to decrypt(),
    so we use the query_id (already in plaintext on the wire) to prevent
    cross-query replay: a ciphertext captured for query A cannot be presented
    as the legitimate payload for query B.
    """
    recipient_pub = X25519PublicKey.from_public_bytes(base64.b64decode(recipient_pubkey_b64))
    ephemeral_priv = X25519PrivateKey.generate()
    shared_secret = ephemeral_priv.exchange(recipient_pub)
    aes_key = _derive_aes_key(shared_secret)
    nonce = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, payload, aad or None)
    ephem_pub_bytes = ephemeral_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(ephem_pub_bytes + nonce + ciphertext).decode()


def decrypt(ciphertext_b64: str, private_key_bytes: bytes, aad: bytes = b"") -> bytes:
    """Decrypt payload using own private key bytes. `aad` must match the
    value passed to encrypt() — typically the query_id."""
    data = base64.b64decode(ciphertext_b64)
    ephem_pub_bytes = data[:32]
    nonce = data[32:44]
    ciphertext = data[44:]
    private_key = X25519PrivateKey.from_private_bytes(private_key_bytes)
    ephem_pub = X25519PublicKey.from_public_bytes(ephem_pub_bytes)
    shared_secret = private_key.exchange(ephem_pub)
    aes_key = _derive_aes_key(shared_secret)
    return AESGCM(aes_key).decrypt(nonce, ciphertext, aad or None)


def pubkey_b64(public_key_bytes: bytes) -> str:
    return base64.b64encode(public_key_bytes).decode()


def pubkey_from_private_b64(private_key_bytes: bytes) -> str:
    """Derive base64 public key from private key bytes."""
    priv = X25519PrivateKey.from_private_bytes(private_key_bytes)
    return pubkey_b64(priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


# ── Publisher signing keys (Ed25519) ──────────────────────────────────────────
# Used by the Hub to sign manifest.sig at deploy time, and by anything that
# needs to expose the local publisher fingerprint to the user. Kept distinct
# from the X25519 encryption keypair above: signing keys live in a separate
# directory and a separate algorithm so the two roles never get conflated.


def load_or_generate_publisher_keypair() -> tuple[str, str]:
    """Return (signing_priv_b64, signing_pub_b64). Generates on first call.

    Returned as base64 strings rather than raw bytes so callers can pass
    them around (config, JSON, env) without thinking about encoding. The
    Hub's deploy flow calls this once per process and threads the priv
    into pack_signing.sign_pack().
    """
    priv_file = paths.publisher_signing_key()
    pub_file = paths.publisher_signing_pub()

    if priv_file.exists() and pub_file.exists():
        _restrict_perms(priv_file, 0o600)
        _restrict_perms(pub_file, 0o644)
        return (
            base64.b64encode(priv_file.read_bytes()).decode(),
            base64.b64encode(pub_file.read_bytes()).decode(),
        )

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    priv_file.write_bytes(priv_bytes)
    _restrict_perms(priv_file, 0o600)
    pub_file.write_bytes(pub_bytes)
    _restrict_perms(pub_file, 0o644)
    return base64.b64encode(priv_bytes).decode(), base64.b64encode(pub_bytes).decode()


def publisher_fingerprint() -> str:
    """Return the local publisher key's short fingerprint, generating the
    keypair if it doesn't exist yet. Useful for the GUI to display 'your
    publisher key: vicky-abc...' without exposing the pubkey itself."""
    from node.pack_signing import fingerprint
    _priv_b64, pub_b64 = load_or_generate_publisher_keypair()
    return fingerprint(pub_b64)


# ── Node identity signing key (Ed25519) ───────────────────────────────────────
# Distinct from both the X25519 encryption pair (peer Critic E2E) and the
# publisher key (pack signing). This one binds a node's identity to a
# private key the broker can challenge: the Trust-On-First-Use table on the
# broker side records the pubkey on first register and refuses any future
# register for the same node_id under a different key.


def load_or_generate_node_signing_keypair() -> tuple[bytes, bytes]:
    """Return (priv_bytes, pub_bytes) — raw 32-byte Ed25519 keys.

    Bytes instead of base64 because the caller usually wants to sign
    immediately (Ed25519PrivateKey.from_private_bytes wants raw). For
    transport (sending the pubkey to the broker) callers can b64-encode.
    """
    priv_file = paths.ed25519_signing_key()
    pub_file = paths.ed25519_signing_pub()

    if priv_file.exists() and pub_file.exists():
        _restrict_perms(priv_file, 0o600)
        _restrict_perms(pub_file, 0o644)
        return priv_file.read_bytes(), pub_file.read_bytes()

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    priv_file.write_bytes(priv_bytes)
    _restrict_perms(priv_file, 0o600)
    pub_file.write_bytes(pub_bytes)
    _restrict_perms(pub_file, 0o644)
    return priv_bytes, pub_bytes


def sign_with_node_key(priv_bytes: bytes, message: bytes) -> bytes:
    """Sign a single message with the node's Ed25519 identity key."""
    return Ed25519PrivateKey.from_private_bytes(priv_bytes).sign(message)
