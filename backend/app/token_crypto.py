from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_key = settings.TOKEN_ENCRYPTION_KEY.strip().encode("ascii")
_fernet = Fernet(_key)


def encrypt_token(plain: str) -> str:
    return _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_token(token_enc: str) -> str:
    try:
        return _fernet.decrypt(token_enc.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Неверный TOKEN_ENCRYPTION_KEY или повреждённые данные") from e
