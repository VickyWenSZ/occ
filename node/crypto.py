from pathlib import Path
import base64, os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256

_KEY_PATH = Path.home() / ".occ_keys"


def load_or_generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes). Generates and persists if not found."""
    _KEY_PATH.mkdir(exist_ok=True)
    priv_file = _KEY_PATH / "private.key"
    pub_file = _KEY_PATH / "public.key"

    if priv_file.exists() and pub_file.exists():
        return priv_file.read_bytes(), pub_file.read_bytes()

    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    priv_file.write_bytes(priv_bytes)
    pub_file.write_bytes(pub_bytes)
    return priv_bytes, pub_bytes


def _derive_aes_key(shared_secret: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=b"occ-v2").derive(shared_secret)


def encrypt(payload: bytes, recipient_pubkey_b64: str) -> str:
    """Encrypt payload for recipient. Returns base64-encoded ciphertext."""
    recipient_pub = X25519PublicKey.from_public_bytes(base64.b64decode(recipient_pubkey_b64))
    ephemeral_priv = X25519PrivateKey.generate()
    shared_secret = ephemeral_priv.exchange(recipient_pub)
    aes_key = _derive_aes_key(shared_secret)
    nonce = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, payload, None)
    ephem_pub_bytes = ephemeral_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(ephem_pub_bytes + nonce + ciphertext).decode()


def decrypt(ciphertext_b64: str, private_key_bytes: bytes) -> bytes:
    """Decrypt payload using own private key bytes."""
    data = base64.b64decode(ciphertext_b64)
    ephem_pub_bytes = data[:32]
    nonce = data[32:44]
    ciphertext = data[44:]
    private_key = X25519PrivateKey.from_private_bytes(private_key_bytes)
    ephem_pub = X25519PublicKey.from_public_bytes(ephem_pub_bytes)
    shared_secret = private_key.exchange(ephem_pub)
    aes_key = _derive_aes_key(shared_secret)
    return AESGCM(aes_key).decrypt(nonce, ciphertext, None)


def pubkey_b64(public_key_bytes: bytes) -> str:
    return base64.b64encode(public_key_bytes).decode()


def pubkey_from_private_b64(private_key_bytes: bytes) -> str:
    """Derive base64 public key from private key bytes."""
    priv = X25519PrivateKey.from_private_bytes(private_key_bytes)
    return pubkey_b64(priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
