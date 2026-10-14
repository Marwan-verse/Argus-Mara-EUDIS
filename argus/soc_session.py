"""Remembered SOC sign-in: the server's token, never the password, in the OS keychain."""
import json

SERVICE, ACCOUNT = "Argus Mara SOC", "remembered sign-in"


def _keychain():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def save(client):
    """Remember the client's sign-in; False when this computer has no usable keychain."""
    keychain = _keychain()
    if keychain is None:
        return False
    value = json.dumps({"url": client.url, "token": client.token,
                        "username": client.user["username"], "ca_file": client.ca_file})
    try:
        keychain.set_password(SERVICE, ACCOUNT, value)
    except Exception:  # Keychain backends raise their own errors; the sign-in is then not remembered.
        return False
    return True


def load():
    keychain = _keychain()
    if keychain is None:
        return None
    try:
        value = json.loads(keychain.get_password(SERVICE, ACCOUNT) or "null")
    except Exception:  # No usable keychain, or an unreadable entry: sign in normally.
        return None
    if not isinstance(value, dict) or not all(isinstance(value.get(key), str) for key in ("url", "token")):
        return None
    return value


def forget():
    keychain = _keychain()
    if keychain is None:
        return
    try:
        keychain.delete_password(SERVICE, ACCOUNT)
    except Exception:  # Nothing was saved, or there is no usable keychain.
        pass
