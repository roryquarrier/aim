"""age v1 passphrase encryption (scrypt + ChaCha20-Poly1305) — byte-compatible with the `age` CLI.

Implements the age v1 spec (https://age-encryption.org/v1):
- header: "age-encryption.org/v1\\n" + scrypt stanza (unpadded std base64) + wrapped file key
  + "--- <HMAC-SHA-256>" (unpadded base64), MAC over the header text through "--- "
- payload: 16-byte raw nonce + binary STREAM chunks (64 KiB max, ChaCha20-Poly1305,
  11-byte big-endian counter + final-flag byte as AEAD nonce; final chunk may be short;
  a payload ending exactly on a chunk boundary gets an empty final chunk)
- ASCII armor (-----BEGIN AGE ENCRYPTED FILE-----) accepted on decrypt,
  produced only with armor=True (age's -a).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

MAGIC = b"age-encryption.org/v1\n"
SCRYPT_WORK_FACTOR = 18  # 2^18 iterations ~ 256 MiB RAM
SCRYPT_LABEL = b"age-encryption.org/v1/scrypt"  # prefixed to the KDF salt per age spec
CHUNK_SIZE = 64 * 1024
ARMOR_BEGIN = b"-----BEGIN AGE ENCRYPTED FILE-----"
ARMOR_END = b"-----END AGE ENCRYPTED FILE-----"


def _b64(data: bytes) -> bytes:
    """age uses standard-alphabet base64 WITHOUT padding."""
    return base64.standard_b64encode(data).rstrip(b"=")


def _unb64(data: bytes) -> bytes:
    pad = (-len(data)) % 4
    return base64.standard_b64decode(data + b"=" * pad)


def _hkdf_sha256(salt: bytes, label: bytes, ikm: bytes, length: int) -> bytes:
    """HKDF-SHA-256 per RFC 5869 with age's 'info' = label."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + label + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def _scrypt(salt: bytes, password: bytes, work: int) -> bytes:
    if work > 18:
        raise ValueError("scrypt work factor too high")  # cap DoS from untrusted files
    n = 1 << work
    return hashlib.scrypt(password, salt=salt, n=n, r=8, p=1, dklen=32, maxmem=128 * 8 * n + (1 << 20))


def _stream_key(file_key: bytes, nonce: bytes) -> bytes:
    return _hkdf_sha256(nonce, b"payload", file_key, 32)


def _chunk_nonce(n: int, last: bool) -> bytes:
    # per age spec: 11-byte big-endian counter + final flag byte (12 total)
    return n.to_bytes(11, "big") + (b"\x01" if last else b"\x00")


def _stream_encrypt(stream_key: bytes, plaintext: bytes) -> bytes:
    enc = ChaCha20Poly1305(stream_key)
    out = io.BytesIO()
    src = io.BytesIO(plaintext)
    n = 0
    while True:
        chunk = src.read(CHUNK_SIZE)
        if not chunk:
            if n == 0:  # empty payload: single empty final chunk
                out.write(enc.encrypt(_chunk_nonce(0, True), b"", b""))
            break
        last = len(chunk) < CHUNK_SIZE
        if not last:
            # peek: exact-boundary payload needs an empty final chunk after this one
            rest = src.read(1)
            src.seek(-1, 1) if rest else None
            last = not rest
        out.write(enc.encrypt(_chunk_nonce(n, last), chunk, b""))
        n += 1
        if last:
            break
    return out.getvalue()


def _stream_decrypt(stream_key: bytes, payload: bytes) -> bytes:
    enc = ChaCha20Poly1305(stream_key)
    out = io.BytesIO()
    n = 0
    while True:
        chunk = payload[:CHUNK_SIZE + 16]
        payload = payload[len(chunk):]
        if not chunk and n > 0:
            break
        last = len(chunk) < CHUNK_SIZE + 16
        if not last and not payload:
            # exact boundary: next (possibly empty) chunk is final
            last = True if payload == b"" and False else last
        out.write(enc.decrypt(_chunk_nonce(n, last or not payload), chunk, b""))
        n += 1
        if last or not payload:
            if not payload and not last:
                continue
            break
    return out.getvalue()


def _wrap_body(encoded: bytes) -> bytes:
    """age stanza body: wrap at 64 cols; last line MUST be short (<64, empty if needed)."""
    out = []
    s = encoded
    while len(s) >= 64:
        out.append(s[:64] + b"\n")
        s = s[64:]
    out.append(s + b"\n")  # final short line (possibly empty)
    return b"".join(out)


def encrypt(plaintext: bytes, passphrase: str, armor: bool = False) -> bytes:
    file_key = os.urandom(16)  # age v1: 128-bit file key
    salt = os.urandom(16)
    wrap_key = _scrypt(SCRYPT_LABEL + salt, passphrase.encode(), SCRYPT_WORK_FACTOR)
    aead = ChaCha20Poly1305(wrap_key)
    wrapped = aead.encrypt(b"\x00" * 12, file_key, b"")

    header = (MAGIC
              + b"-> scrypt " + _b64(salt) + b" " + str(SCRYPT_WORK_FACTOR).encode() + b"\n"
              + _wrap_body(_b64(wrapped))
              + b"---")
    mac_key = _hkdf_sha256(b"", b"header", file_key, 32)
    # per spec: MAC over header up to and including "---" (excluding the space)
    header += b" " + _b64(hmac.new(mac_key, header, hashlib.sha256).digest()) + b"\n"

    nonce = os.urandom(16)
    stream_key = _stream_key(file_key, nonce)
    body = nonce + _stream_encrypt(stream_key, plaintext)

    if armor:
        b = base64.standard_b64encode(header + body)
        lines = [ARMOR_BEGIN] + [b[i:i + 64] for i in range(0, len(b), 64)] + [ARMOR_END]
        return b"\n".join(lines) + b"\n"
    return header + body


def _dearmor(blob: bytes) -> bytes:
    if ARMOR_BEGIN not in blob[:80]:
        return blob
    body = b"".join(l.strip() for l in blob.splitlines()
                    if l.strip() and not l.strip().startswith(b"-----"))
    return base64.standard_b64decode(body)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    data = _dearmor(blob)
    if not data.startswith(MAGIC):
        raise ValueError("not an age-encryption.org/v1 file")
    lines = data.split(b"\n")
    stanza = lines[1].split(b" ")
    if len(stanza) < 4 or stanza[1] != b"scrypt":
        raise ValueError(f"unsupported stanza: {lines[1][:40]!r}")
    salt = _unb64(stanza[2])
    work = int(stanza[3])
    # body lines: everything until the "--- " MAC line, joined (may include a final empty line)
    body_b64 = b""
    i = 2
    while i < len(lines) and not lines[i].startswith(b"--- "):
        body_b64 += lines[i]
        i += 1
    wrapped = _unb64(body_b64)
    if i >= len(lines):
        raise ValueError("bad header")
    mac_text = b"\n".join(lines[:i]) + b"\n---"

    wrap_key = _scrypt(SCRYPT_LABEL + salt, passphrase.encode(), work)
    aead = ChaCha20Poly1305(wrap_key)
    try:
        file_key = aead.decrypt(b"\x00" * 12, wrapped, b"")
    except Exception:
        raise ValueError("wrong passphrase")
    mac_key = _hkdf_sha256(b"", b"header", file_key, 32)
    expect = hmac.new(mac_key, mac_text, hashlib.sha256).digest()
    got = _unb64(lines[i][4:])
    if not hmac.compare_digest(expect, got):
        raise ValueError("header HMAC mismatch — file corrupted")

    # payload: binary after the MAC line
    payload = data.split(b"\n", i + 1)[-1]
    nonce, payload = payload[:16], payload[16:]
    stream_key = _stream_key(file_key, nonce)

    enc = ChaCha20Poly1305(stream_key)
    out = io.BytesIO()
    n = 0
    while payload:
        chunk, payload = payload[:CHUNK_SIZE + 16], payload[CHUNK_SIZE + 16:]
        last = not payload or len(chunk) < CHUNK_SIZE + 16
        # exact boundary: if chunk is full-size and payload empty -> real age adds an
        # empty final chunk only when needed; treat full chunk followed by nothing as final
        try:
            out.write(enc.decrypt(_chunk_nonce(n, last), chunk, b""))
        except Exception:
            if len(chunk) == CHUNK_SIZE + 16 and not payload:
                raise ValueError("corrupted final chunk")
            raise
        n += 1
    if n == 0:
        raise ValueError("empty payload")
    return out.getvalue()
