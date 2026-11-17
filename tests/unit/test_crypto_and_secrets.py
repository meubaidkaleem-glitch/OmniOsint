from __future__ import annotations

import json
import sys

import pytest

from omniosint.core.crypto import KEY_BYTES, DecryptionError, SecretBox, generate_key
from omniosint.core.keystore import FilePermissionProtector, KeyProtectionError, MasterKeyStore
from omniosint.core.paths import AppPaths, is_owner_only
from omniosint.core.secrets import SecretStore, SecretStoreError, validate_secret_name


def test_secretbox_round_trip_and_random_nonce() -> None:
    box = SecretBox(generate_key())
    first = box.encrypt(b"payload", aad=b"name")
    second = box.encrypt(b"payload", aad=b"name")
    assert first != second
    assert box.decrypt(first, aad=b"name") == b"payload"


def test_secretbox_detects_tampering() -> None:
    box = SecretBox(generate_key())
    token = bytearray(box.encrypt(b"payload"))
    token[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        box.decrypt(bytes(token))


def test_secretbox_binds_associated_data() -> None:
    box = SecretBox(generate_key())
    token = box.encrypt_text("value", aad="database.password")
    with pytest.raises(DecryptionError):
        box.decrypt_text(token, aad="provider.shodan")


def test_secretbox_rejects_wrong_key_and_garbage() -> None:
    token = SecretBox(generate_key()).encrypt(b"payload")
    with pytest.raises(DecryptionError):
        SecretBox(generate_key()).decrypt(token)
    with pytest.raises(DecryptionError):
        SecretBox(generate_key()).decrypt(b"short")
    with pytest.raises(DecryptionError):
        SecretBox(generate_key()).decrypt_text("!!not base64!!")
    with pytest.raises(ValueError, match="bytes"):
        SecretBox(b"too-short")


def test_master_key_is_created_once_and_reused(app_paths: AppPaths) -> None:
    store = MasterKeyStore(app_paths.secrets_dir)
    key = store.load_or_create()
    assert len(key) == KEY_BYTES
    assert MasterKeyStore(app_paths.secrets_dir).load_or_create() == key


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_master_key_file_is_owner_only(app_paths: AppPaths) -> None:
    store = MasterKeyStore(app_paths.secrets_dir, FilePermissionProtector())
    store.load_or_create()
    assert is_owner_only(store.path) is True


def test_master_key_from_another_protector_is_refused(app_paths: AppPaths) -> None:
    store = MasterKeyStore(app_paths.secrets_dir)
    store.load_or_create()
    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["protector"] = "dpapi" if store.protector.name != "dpapi" else "file-permissions"
    store.path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(KeyProtectionError, match="another machine or account"):
        MasterKeyStore(app_paths.secrets_dir).load_or_create()


def test_corrupt_master_key_is_reported(app_paths: AppPaths) -> None:
    store = MasterKeyStore(app_paths.secrets_dir)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(KeyProtectionError, match="unreadable or corrupt"):
        store.load_or_create()


def test_secret_store_round_trip(app_paths: AppPaths) -> None:
    store = SecretStore(app_paths)
    assert store.get("database.password") is None
    store.set("database.password", "pa55-word")
    assert store.get("database.password") == "pa55-word"
    assert store.names() == ["database.password"]
    described = store.describe()
    assert described[0]["name"] == "database.password"
    assert "pa55-word" not in json.dumps(described)
    assert store.delete("database.password") is True
    assert store.delete("database.password") is False
    assert store.get("database.password") is None


def test_secret_values_are_not_stored_in_clear(app_paths: AppPaths) -> None:
    store = SecretStore(app_paths)
    store.set("provider.example", "plain-text-canary-value")
    assert "plain-text-canary-value" not in store.path.read_text(encoding="utf-8")


def test_secret_moved_to_another_name_cannot_be_decrypted(app_paths: AppPaths) -> None:
    store = SecretStore(app_paths)
    store.set("a.secret", "value-a")
    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["secrets"]["b.secret"] = document["secrets"]["a.secret"]
    store.path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SecretStoreError, match="could not be decrypted"):
        store.get("b.secret")


@pytest.mark.parametrize("name", ["", "UPPER", "with space", "../escape", "x" * 200])
def test_invalid_secret_names(name: str) -> None:
    with pytest.raises(ValueError, match="Secret names"):
        validate_secret_name(name)


def test_empty_secret_value_is_refused(app_paths: AppPaths) -> None:
    with pytest.raises(ValueError, match="empty"):
        SecretStore(app_paths).set("database.password", "")


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")
def test_dpapi_round_trip(app_paths: AppPaths) -> None:
    from omniosint.core.keystore import default_protector

    protector = default_protector()
    assert protector.name == "dpapi"
    wrapped = protector.protect(b"0123456789abcdef0123456789abcdef")
    assert wrapped != b"0123456789abcdef0123456789abcdef"
    assert protector.unprotect(wrapped) == b"0123456789abcdef0123456789abcdef"
    store = SecretStore(app_paths)
    store.set("database.password", "dpapi-protected")
    assert SecretStore(app_paths).get("database.password") == "dpapi-protected"
