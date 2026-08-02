"""Govee GATT packet encryption (newer firmware auth handshake).

Newer H5075/H5179 firmwares expose service
``00010203-0405-0607-0809-0a0b0c0d1910`` and require an AES/RC4 session
before history commands are accepted. Protocol details from community
reverse-engineering (GoveeBTTempLogger / openHAB bluetooth.govee).
"""

from __future__ import annotations

from Crypto.Cipher import AES, ARC4

# Hardcoded 16-byte PSK from the Govee Home app: "MakingLifeSmarte"
PRESHARED_KEY = b"MakingLifeSmarte"

UUID_AUTH_SERVICE = "00010203-0405-0607-0809-0a0b0c0d1910"
UUID_AUTH_NOTIFY = "00010203-0405-0607-0809-0a0b0c0d2b10"
UUID_AUTH_WRITE = "00010203-0405-0607-0809-0a0b0c0d2b11"


def xor_checksum_byte(payload: bytes) -> int:
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF


def with_checksum(packet: bytes | bytearray) -> bytes:
    """Return a 20-byte packet with XOR checksum in the last byte."""
    buf = bytearray(packet)
    if len(buf) < 20:
        buf.extend(b"\x00" * (20 - len(buf)))
    elif len(buf) > 20:
        buf = buf[:20]
    buf[19] = xor_checksum_byte(buf[:19])
    return bytes(buf)


def encrypt_packet(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB on bytes 0-15, RC4 on bytes 16-19 (no padding)."""
    if len(plaintext) != 20:
        raise ValueError("Govee GATT packets must be 20 bytes")
    if len(key) != 16:
        raise ValueError("Govee key must be 16 bytes")
    aes_part = AES.new(key, AES.MODE_ECB).encrypt(plaintext[:16])
    rc4_part = ARC4.new(key).encrypt(plaintext[16:20])
    return aes_part + rc4_part


def decrypt_packet(ciphertext: bytes, key: bytes) -> bytes:
    """AES-128-ECB decrypt bytes 0-15, RC4 (symmetric) on bytes 16-19."""
    if len(ciphertext) != 20:
        raise ValueError("Govee GATT packets must be 20 bytes")
    if len(key) != 16:
        raise ValueError("Govee key must be 16 bytes")
    aes_part = AES.new(key, AES.MODE_ECB).decrypt(ciphertext[:16])
    rc4_part = ARC4.new(key).encrypt(ciphertext[16:20])
    return aes_part + rc4_part


def seal(packet: bytes | bytearray, key: bytes | None) -> bytes:
    """Checksum then optionally encrypt a 20-byte command packet."""
    plain = with_checksum(packet)
    if key is None:
        return plain
    return encrypt_packet(plain, key)


def open_packet(packet: bytes, key: bytes | None) -> bytes:
    """Optionally decrypt a 20-byte notification payload."""
    if key is None or len(packet) != 20:
        return bytes(packet)
    return decrypt_packet(packet, key)
