import os
import json
import hashlib
from pathlib import Path
from Crypto.Cipher import AES



OBJKEY_PREFIX = "\0ES3OBJKEY:"
BLOCK_SIZE = AES.block_size



class EasySave3:
    def __init__(self, password):
        self.password = password.encode("utf-8")


    def _make_key(self, iv):
        return hashlib.pbkdf2_hmac("sha1", self.password, iv, 100, dklen=BLOCK_SIZE)


    def _pad(self, data):
        pad_len = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
        return data + bytes([pad_len] * pad_len)


    def _unpad(self, data):
        if not data:
            raise ES3Error("Invalid padding: empty data.")

        pad = data[-1]
        if not 1 <= pad <= BLOCK_SIZE:
            raise ES3Error("Invalid PKCS#7 padding.")

        if data[-pad:] != bytes([pad]) * pad:
            raise ES3Error("Invalid PKCS#7 padding.")

        return data[:-pad]


    def decrypt(self, path):
        """Decrypt an EasySave3 file. Raises ES3Error on invalid data."""
        data = Path(path).read_bytes()

        if len(data) < BLOCK_SIZE * 2:
            raise ES3Error("Invalid EasySave3 file: too short.")
        
        iv = data[:BLOCK_SIZE]
        ciphertext = data[BLOCK_SIZE:]

        if len(ciphertext) % BLOCK_SIZE != 0:
            raise ES3Error("Invalid ciphertext length.")
        
        cipher = AES.new(self._make_key(iv), AES.MODE_CBC, iv)
        return self._unpad(cipher.decrypt(ciphertext))

    
    def encrypt(self, data):
        iv = os.urandom(BLOCK_SIZE)
        cipher = AES.new(self._make_key(iv), AES.MODE_CBC, iv)
        return iv + cipher.encrypt(self._pad(data))


    def load(self, input_path):
        """Load and decrypt an EasySave3 file."""
        decrypted = self.decrypt(input_path)

        try:
            text = decrypted.decode("utf-8").strip("\x00")
        except UnicodeDecodeError as e:
            raise ES3Error("Save data is not valid UTF-8.") from e

        return es3_loads(text)


    def save(self, data, output_path):
        """Encrypt and save a data dictionary."""
        es3_text = es3_dumps(data)
        encrypted = self.encrypt(es3_text.encode("utf-8"))
        Path(output_path).write_bytes(encrypted)
        print(f"Encrypted to {output_path}")


    def import_json(self, input_path, output_path):
        """Import JSON and save it as an EasySave3 file."""
        try:
            data = json.loads(Path(input_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ES3Error(f"Invalid JSON file: {e}") from e
        
        self.save(data, output_path)


    def export_json(self, data, output_path, indent=4):
        """Export parsed save data to a JSON file."""
        try:
            json_text = json.dumps(data, indent=indent, ensure_ascii=False)
        except TypeError as e:
            raise ES3Error(f"Cannot serialize data to JSON: {e}") from e
        
        Path(output_path).write_text(json_text, encoding="utf-8")
        print(f"Exported JSON to {output_path}")



class ES3Error(Exception):
    """Base exception for EasySave3 operations."""
    pass



def es3_loads(text):
    """Parse ES3-flavored JSON (supports bare numeric keys and object keys)."""
    return _Parser(text).parse()



def es3_dumps(obj, indent=0):
    """Serialize Python object to ES3-flavored JSON."""
    buf = []
    _dump_value(obj, buf, indent, 0)
    return "".join(buf)



class _Parser:
    def __init__(self, text):
        self.text = text
        self.i = 0
        self.n = len(text)


    def parse(self):
        self._skip_ws()
        value = self._parse_value()
        self._skip_ws()

        if not isinstance(value, dict):
            self._err("Root value must be an object")
        
        # Reject trailing garbage, ew yucky stinky
        if self.i != self.n:
            self._err("Unexpected trailing data")
        
        return value


    def _skip_ws(self):
        while self.i < self.n and self.text[self.i] in " \t\n\r":
            self.i += 1


    def _peek(self):
        return self.text[self.i] if self.i < self.n else ""


    def _err(self, msg):
        # Show context around error because it's yknow.. useful
        start = max(0, self.i - 20)
        end = min(self.n, self.i + 20)
        context = self.text[start:end]
        raise ES3Error(f"{msg} at position {self.i} (near: ...{context}...)")


    def _parse_value(self):
        # have fun reading this garbage future me! :D
        ch = self._peek()
        if ch == "{": return self._parse_object()
        if ch == "[": return self._parse_array()
        if ch == '"': return self._parse_string()
        if ch == "-" or ch.isdigit(): return self._parse_number()
        if self.text.startswith("true", self.i): self.i += 4; return True
        if self.text.startswith("false", self.i): self.i += 5; return False
        if self.text.startswith("null", self.i): self.i += 4; return None
        self._err(f"Unexpected character {ch!r}")


    def _parse_object(self):
        self.i += 1
        obj = {}
        self._skip_ws()
        if self._peek() == "}": self.i += 1; return obj
        
        # and this too
        while True:
            self._skip_ws()
            key = self._parse_key()
            self._skip_ws()
            if self._peek() != ":": self._err("Expected ':'")
            self.i += 1
            self._skip_ws()
            obj[key] = self._parse_value()
            self._skip_ws()
            ch = self._peek()
            if ch == ",": self.i += 1; continue
            if ch == "}": self.i += 1; break
            self._err("Expected ',' or '}'")
        return obj


    def _parse_key(self):
        ch = self._peek()
        if ch == '"': return self._parse_string()
        if ch == "{": return OBJKEY_PREFIX + json.dumps(self._parse_object(), separators=(",", ":"), ensure_ascii=False)
        if ch == "-" or ch.isdigit():
            start = self.i
            self._consume_number()
            return self.text[start:self.i]
        self._err(f"Unexpected key start {ch!r}")


    def _parse_number(self):
        start = self.i
        self._consume_number()
        raw = self.text[start:self.i]

        # Check for float
        if any(c in raw for c in ".eE"):
            return float(raw)
        return int(raw)


    def _parse_array(self):
        self.i += 1
        arr = []
        self._skip_ws()
        if self._peek() == "]": self.i += 1; return arr
        while True:
            self._skip_ws()
            arr.append(self._parse_value())
            self._skip_ws()
            ch = self._peek()
            if ch == ",": self.i += 1; continue
            if ch == "]": self.i += 1; break
            self._err("Expected ',' or ']'")
        return arr


    def _parse_string(self):
        # This is some of my worst work yet, yippee!!
        self.i += 1
        chars = []

        while self.i < self.n:
            ch = self.text[self.i]
            if ch == '"':
                self.i += 1
                return "".join(chars)
            if ch == "\\":
                self.i += 1
                if self.i >= self.n:
                    self._err("Unterminated escape sequence")

                esc = self.text[self.i]

                if esc in '"\\/bfnrt':
                    chars.append({
                        '"': '"',
                        "\\": "\\",
                        "/": "/",
                        "b": "\b",
                        "f": "\f",
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                    }[esc])
                    self.i += 1
                elif esc == "u":
                    if self.i + 4 >= self.n:
                        self._err("Incomplete unicode escape")

                    try:
                        code_point = int(self.text[self.i + 1:self.i + 5], 16)
                        consumed = 5  # 'u' + 4 hex digits

                        if 0xD800 <= code_point <= 0xDBFF:
                            if (self.i + 10 < self.n and self.text[self.i + 5:self.i + 7] == "\\u"):
                                low_code = int(self.text[self.i + 7:self.i + 11], 16)

                                if 0xDC00 <= low_code <= 0xDFFF:
                                    combined = (0x10000 + ((code_point - 0xD800) << 10) + (low_code - 0xDC00))
                                    chars.append(chr(combined))
                                    consumed = 11  # 'u' + 4 hex + '\u' + 4 hex
                                else:
                                    chars.append(chr(code_point))
                            else:
                                chars.append(chr(code_point))
                        else:
                            chars.append(chr(code_point))

                    except ValueError:
                        self._err("Invalid unicode escape")

                    self.i += consumed
            else:
                chars.append(ch)
                self.i += 1

        self._err("Unterminated string")


    def _consume_number(self):
        if self._peek() == "-":
            self.i += 1
        
        # Integer
        if not self._peek().isdigit():
            self._err("Malformed number")
        while self.i < self.n and self.text[self.i].isdigit():
            self.i += 1

        # Fraction
        if self._peek() == ".":
            self.i += 1
            if not self._peek().isdigit():
                self._err("Malformed number")
            while self.i < self.n and self.text[self.i].isdigit():
                self.i += 1

        # Exponent
        if self._peek() in ("e", "E"):
            self.i += 1
            if self._peek() in ("+", "-"):
                self.i += 1
            if not self._peek().isdigit():
                self._err("Malformed exponent")
            while self.i < self.n and self.text[self.i].isdigit():
                self.i += 1



def _dump_value(value, buf, indent, level):
    if isinstance(value, dict):
        if not value:
            buf.append("{}")
            return

        nl = "\n" if indent else ""
        buf.append("{" + nl)
        items = list(value.items())
        last = len(items) - 1

        for idx, (k, v) in enumerate(items):
            if indent:
                buf.append(" " * (indent * (level + 1)))

            if isinstance(k, str) and k.startswith(OBJKEY_PREFIX):
                _dump_value(json.loads(k[len(OBJKEY_PREFIX):]), buf, indent, level + 1)
            elif isinstance(k, str) and k.lstrip("-").isdigit():
                buf.append(k)
            else:
                buf.append(json.dumps(k, ensure_ascii=False))

            buf.append(" : " if indent else ":")
            _dump_value(v, buf, indent, level + 1)

            if idx != last:
                buf.append(",")
            buf.append(nl)

        if indent:
            buf.append(" " * (indent * level))
        buf.append("}")

    elif isinstance(value, list):
        if not value:
            buf.append("[]")
            return

        nl = "\n" if indent else ""
        buf.append("[" + nl)
        last = len(value) - 1

        for idx, v in enumerate(value):
            if indent:
                buf.append(" " * (indent * (level + 1)))

            _dump_value(v, buf, indent, level + 1)

            if idx != last:
                buf.append(",")
            buf.append(nl)

        if indent:
            buf.append(" " * (indent * level))
        buf.append("]")

    elif isinstance(value, str):
        buf.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, bool):
        buf.append("true" if value else "false")
    elif isinstance(value, int):
        buf.append(str(value))
    elif isinstance(value, float):
        buf.append(repr(value))
    elif value is None:
        buf.append("null")
    else:
        raise ES3Error(f"Cannot serialize {type(value)}")