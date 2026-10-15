"""age-style passphrase encryption (scrypt + ChaCha20-Poly1305).

NOTE: this is an AIM-internal format inspired by the age v1 spec — it is NOT
byte-compatible with the `age` CLI (padded base64, 32-byte file key, text
chunks). Interoperability with the age tool is a v1.2 goal.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

MAGIC = b"age-encryption.org/v1\n"
SCRYPT_WORK_FACTOR = 18  # 2^18 iterations ~ 256 MiB RAM
CHUNK_SIZE = 64 * 1024
TAG_SIZE = 16


def _b64(data: bytes) -> bytes:
    return base64.standard_b64encode(data)


def _unb64(data: bytes) -> bytes:
    return base64.standard_b64decode(data)


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
    if work > 20:
        raise ValueError("scrypt work factor too high")  # cap DoS from untrusted files
    n = 1 << work
    return hashlib.scrypt(password, salt=salt, n=n, r=8, p=1, dklen=32, maxmem=128 * 8 * n + (1 << 20))


def _stream_key(file_key: bytes, nonce: bytes) -> bytes:
    return _hkdf_sha256(nonce, b"payload", file_key, 32)


def _chunk(n: int, last: bool) -> bytes:
    # per age spec: nonce = 11-byte big-endian counter + final flag byte (12 total)
    return n.to_bytes(11, "big") + (b"\x01" if last else b"\x00")


def encrypt(plaintext: bytes, passphrase: str) -> bytes:
    file_key = os.urandom(32)
    salt = os.urandom(16)
    wrap_key = _scrypt(salt, passphrase.encode(), SCRYPT_WORK_FACTOR)
    aead = ChaCha20Poly1305(wrap_key)
    body = _b64(aead.encrypt(b"\x00"*12, file_key, b"")) + b"\n"

    header = MAGIC + b"-> scrypt " + _b64(salt) + b" " + str(SCRYPT_WORK_FACTOR).encode() + b"\n" + body
    mac_key = _hkdf_sha256(b"", b"header", file_key, 32)
    hmac_v = hmac.new(mac_key, header, hashlib.sha256).digest()
    header += b"--- " + _b64(hmac_v) + b"\n"

    nonce = os.urandom(16)
    stream_key = _stream_key(file_key, nonce)
    enc = ChaCha20Poly1305(stream_key)
    out = io.BytesIO()
    out.write(header)
    out.write(_b64(nonce) + b"\n")
    plaintext_stream = io.BytesIO(plaintext)
    n = 0
    while True:
        chunk_data = plaintext_stream.read(CHUNK_SIZE)
        if not chunk_data:
            if n == 0:
                # empty payload: single empty final chunk
                out.write(_b64(enc.encrypt(_chunk(0, True), b"", b"")) + b"\n")
            break
        # final iff fewer bytes follow
        last = plaintext_stream.read(1) == b""
        if not last:
            plaintext_stream.seek(-1, 1)
        out.write(_b64(enc.encrypt(_chunk(n, last), chunk_data, b"")) + b"\n")
        n += 1
        if last:
            break
    return out.getvalue()


def decrypt(blob: bytes, passphrase: str) -> bytes:
    lines = blob.split(b"\n")
    if lines[0] + b"\n" != MAGIC:
        raise ValueError("not an age-encryption.org/v1 file")
    stanza = lines[1]
    parts = stanza.split(b" ")
    if parts[1] != b"scrypt":
        raise ValueError(f"unsupported stanza: {parts[1].decode()}")
    salt = _unb64(parts[2])
    work = int(parts[3])
    wrapped = _unb64(lines[2])
    header = MAGIC + lines[1] + b"\n" + lines[2] + b"\n"
    hmac_line = lines[3]
    if not hmac_line.startswith(b"--- "):
        raise ValueError("bad header")
    # verify HMAC with file key after unwrap
    wrap_key = _scrypt(salt, passphrase.encode(), work)
    aead = ChaCha20Poly1305(wrap_key)
    try:
        file_key = aead.decrypt(b"\x00"*12, wrapped, b"")
    except Exception:
        raise ValueError("wrong passphrase")
    mac_key = _hkdf_sha256(b"", b"header", file_key, 32)
    expect = hmac.new(mac_key, header, hashlib.sha256).digest()
    got = _unb64(hmac_line[4:])
    if not hmac.compare_digest(expect, got):
        raise ValueError("header HMAC mismatch — file corrupted")
    nonce = _unb64(lines[4])
    stream_key = _stream_key(file_key, nonce)
    dec = ChaCha20Poly1305(stream_key)
    out = io.BytesIO()
    payload = [l for l in lines[5:] if l]  # drop empty trailing
    for i, line in enumerate(payload):
        is_last = i == len(payload) - 1  # age spec: only the final chunk has the last flag
        ct = _unb64(line)
        pt = dec.decrypt(_chunk(i, is_last), ct, b"")
        out.write(pt)
    return out.getvalue()
