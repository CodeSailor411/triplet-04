"""Create the local Brain TLS identity, separate from Guardian's action-signing keys."""

import ipaddress
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _replace(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_tls(key_path: Path, cert_path: Path) -> None:
    now = datetime.now(timezone.utc)
    if key_path.exists() and cert_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        if key.public_key() != cert.public_key():
            raise ValueError("Brain TLS volumes contain mismatched files; restore the matching pair")
        if cert.not_valid_after_utc <= now:
            raise ValueError("Brain TLS certificate expired; recreate the two CIVIS TLS volumes")
        return
    if key_path.exists() or cert_path.exists():
        raise ValueError("Brain TLS volume pair is incomplete; restore or recreate both CIVIS TLS volumes")

    key = ec.generate_private_key(ec.SECP256R1())
    identity = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "brain")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(identity)
        .issuer_name(identity)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("brain"), x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    _replace(key_path, key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ), 0o600)
    _replace(cert_path, cert.public_bytes(serialization.Encoding.PEM), 0o644)


if __name__ == "__main__":
    ensure_tls(Path("/run/civis-tls/brain.key"), Path("/run/civis-ca/brain.crt"))
