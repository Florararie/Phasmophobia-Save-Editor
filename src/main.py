import os
import re
import json
import hashlib
import pathlib
from Crypto.Cipher import AES



class EasySave3:
    BLOCK_SIZE = 16
    def __init__(self, password: str):
        self.password = password.encode("utf-8")


    @staticmethod
    def _pad(data: bytes) -> bytes:
        pad_len = EasySave3.BLOCK_SIZE - (len(data) % EasySave3.BLOCK_SIZE)
        return data + bytes([pad_len] * pad_len)


    @staticmethod
    def _unpad(data: bytes) -> bytes:
        return data[:-data[-1]]


    @staticmethod
    def _make_key(password: bytes, iv: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha1", password, iv, 100, dklen=EasySave3.BLOCK_SIZE)


    @staticmethod
    def _add_quotes_to_numeric_keys(es3_text: str) -> str:
        """Convert {12:2} -> {"12":2} for valid JSON."""
        return re.sub(r'([{,]\s*)(\d+)(\s*:)', r'\1"\2"\3', es3_text)


    @staticmethod
    def _remove_quotes_from_numeric_keys(json_text: str) -> str:
        """Convert {"12":2} -> {12:2} for EasySave3."""
        return re.sub(r'([{,]\s*)"(\d+)"(\s*:)', r'\1\2\3', json_text)


    def decrypt(self, input_path: str) -> bytes:
        data = pathlib.Path(input_path).read_bytes()
        iv, ciphertext = data[:16], data[16:]
        key = self._make_key(self.password, iv)

        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(ciphertext)
        return self._unpad(decrypted)


    def decrypt_to_json(self, input_path: str, json_path: str):
        decrypted_data = self.decrypt(input_path)
        text = decrypted_data.decode("utf-8", errors="ignore").strip("\x00").strip()
        text = re.sub(r'[\x00-\x1F\x7F-\x9F]+$', "", text)
        json_text = self._add_quotes_to_numeric_keys(text)

        try:
            parsed = json.loads(json_text)
            formatted = json.dumps(parsed, indent=4)
            pathlib.Path(json_path).write_text(formatted, encoding="utf-8")
            print(f"Valid JSON written to {json_path}")
        except json.JSONDecodeError:
            pathlib.Path(json_path).write_text(json_text, encoding="utf-8")
            print(f"Warning: File decrypted but not valid JSON. Wrote raw text to {json_path}")


    def encrypt(self, data: bytes) -> bytes:
        iv = os.urandom(self.BLOCK_SIZE)
        key = self._make_key(self.password, iv)

        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(self._pad(data))
        return iv + encrypted


    def encrypt_from_json(self, json_path: str, output_path: str):
        json_text = pathlib.Path(json_path).read_text(encoding="utf-8")
        es3_text = self._remove_quotes_from_numeric_keys(json_text)
        data = es3_text.encode("utf-8")

        encrypted_data = self.encrypt(data)
        pathlib.Path(output_path).write_bytes(encrypted_data)
        print(f"Re-encrypted and saved as {output_path}")
