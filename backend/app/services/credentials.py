"""Encrypt persisted credentials; back up the key with the database."""
from pathlib import Path
from cryptography.fernet import Fernet
from app.config import DATA_DIR


def _cipher() -> Fernet:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / ".credentials_key"
    try:
        with path.open("xb") as out:
            out.write(Fernet.generate_key())
        path.chmod(0o600)
    except FileExistsError:
        pass
    return Fernet(path.read_bytes())


def seal(value: str) -> str:
    if not value or value.startswith("enc:v1:"):
        return value
    return "enc:v1:" + _cipher().encrypt(value.encode()).decode()


def unseal(value: str) -> str:
    if not value.startswith("enc:v1:"):
        return value
    return _cipher().decrypt(value[7:].encode()).decode()
