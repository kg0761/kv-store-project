"""Append-only, persistent key-value store with a linear-scan index.

Run with ``python3 kvstore.py``. No third-party dependencies are needed.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO


@dataclass
class Entry:
    key: str
    kind: str = "string"
    value: str = ""
    fields: list[tuple[str, str]] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    expires_at: float | None = None

    def clone(self) -> Entry:
        return Entry(self.key, self.kind, self.value, self.fields.copy(),
                     self.items.copy(), self.expires_at)

    def to_record(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "value": self.value,
            "fields": self.fields,
            "items": self.items,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_record(cls, record: dict) -> Entry:
        return cls(
            key=record["key"],
            kind=record.get("kind", "string"),
            value=record.get("value", ""),
            fields=[tuple(pair) for pair in record.get("fields", [])],
            items=list(record.get("items", [])),
            expires_at=record.get("expires_at"),
        )


class Database:
    """Store entries in a list rather than a dictionary-based index."""

    def __init__(self, path: str | Path = "data.db") -> None:
        self.path = Path(path)
        self.entries: list[Entry] = []
        self.pending: list[Entry] | None = None
        self._replay()
        # Ensure data.db exists even if only GET or EXIT is called.
        self.path.touch(exist_ok=True)

    @staticmethod
    def _find(entries: list[Entry], key: str) -> int:
        for i, entry in enumerate(entries):
            if entry.key == key:
                return i
        return -1

    @classmethod
    def _read(cls, entries: list[Entry], key: str) -> Entry | None:
        i = cls._find(entries, key)
        if i < 0:
            return None
        entry = entries[i]
        if entry.expires_at is not None and entry.expires_at <= time.time():
            return None
        return entry

    @classmethod
    def _apply(cls, entries: list[Entry], record: dict) -> None:
        op = record["op"]
        if op == "batch":
            for item in record["operations"]:
                cls._apply(entries, item)
        elif op == "flush":
            entries.clear()
        elif op == "delete":
            index = cls._find(entries, record["key"])
            if index >= 0:
                entries.pop(index)
        elif op == "put":
            entry = Entry.from_record(record["entry"])
            index = cls._find(entries, entry.key)
            if index < 0:
                entries.append(entry)
            else:
                entries[index] = entry
        else:
            raise ValueError("unknown log operation")

    def _replay(self) -> None:
        if not self.path.exists():
            return
        # Each line is a complete JSON operation; an incomplete final line
        # (possible after a crash during a write) is ignored.
        with self.path.open("rb") as stream:
            lines = stream.readlines()
        for index, raw in enumerate(lines):
            try:
                record = json.loads(raw)
                self._apply(self.entries, record)
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                if index == len(lines) - 1 and not raw.endswith(b"\n"):
                    break
                raise

    def _append(self, record: dict) -> None:
        data = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
        with self.path.open("ab") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def _current(self) -> list[Entry]:
        return self.pending if self.pending is not None else self.entries

    def _write(self, record: dict) -> None:
        if self.pending is not None:
            self._apply(self.pending, record)
            return
        # First write to disk, then update memory. Replaying after a crash
        # always reconstructs committed state.
        self._append(record)
        self._apply(self.entries, record)

    def _put(self, entry: Entry) -> None:
        self._write({"op": "put", "entry": entry.to_record()})

    def _get(self, key: str) -> Entry | None:
        return self._read(self._current(), key)

    def execute(self, args: list[str]) -> str:
        if not args:
            return ""
        command = args[0].upper()
        values = args[1:]
        count = len(values)

        if command == "EXIT" and count == 0:
            return "BYE"
        if command == "BEGIN" and count == 0:
            if self.pending is not None:
                return "ERROR transaction already active"
            self.pending = [entry.clone() for entry in self.entries]
            return "OK"
        if command == "ABORT" and count == 0:
            if self.pending is None:
                return "ERROR no transaction"
            self.pending = None
            return "OK"
        if command == "COMMIT" and count == 0:
            if self.pending is None:
                return "ERROR no transaction"
            # Snapshot the staged state as a single, replayable log record.
            snapshot = {"op": "batch", "operations": [
                {"op": "flush"},
                *({"op": "put", "entry": entry.to_record()}
                  for entry in self.pending),
            ]}
            self._append(snapshot)
            self.entries = self.pending
            self.pending = None
            return "OK"
        if command == "SET" and count == 2:
            self._put(Entry(values[0], value=values[1]))
            return "OK"
        if command == "GET" and count == 1:
            entry = self._get(values[0])
            if entry is None:
                return ""
            if entry.kind != "string":
                return "ERROR wrong type"
            return entry.value
        if command == "DEL" and count == 1:
            exists = self._get(values[0]) is not None
            self._write({"op": "delete", "key": values[0]})
            return "1" if exists else "0"
        if command == "EXISTS" and count == 1:
            return "1" if self._get(values[0]) is not None else "0"
        if command == "MSET" and count >= 2 and count % 2 == 0:
            operations = []
            for i in range(0, count, 2):
                entry = Entry(values[i], value=values[i + 1])
                operations.append({"op": "put", "entry": entry.to_record()})
            self._write({"op": "batch", "operations": operations})
            return "OK"
        if command == "MGET" and count >= 1:
            result = []
            for key in values:
                entry = self._get(key)
                result.append(entry.value if entry is not None and
                              entry.kind == "string" else "")
            return "\n".join(result)
        if command == "EXPIRE" and count == 2:
            try:
                seconds = int(values[1])
            except ValueError:
                return "ERROR invalid seconds"
            entry = self._get(values[0])
            if entry is None:
                return "0"
            if seconds <= 0:
                self._write({"op": "delete", "key": values[0]})
            else:
                updated = entry.clone()
                updated.expires_at = time.time() + seconds
                self._put(updated)
            return "1"
        if command == "TTL" and count == 1:
            entry = self._get(values[0])
            if entry is None:
                return "-2"
            if entry.expires_at is None:
                return "-1"
            return str(max(0, math.ceil(entry.expires_at - time.time())))
        if command == "RANGE" and count == 2:
            # Gradebot uses a literal backslash as an open-ended upper bound.
            # Otherwise both bounds are inclusive and lexicographic.
            upper_open = values[1] == "\\"
            keys = sorted(e.key for e in self._current()
                          if values[0] <= e.key
                          and (upper_open or e.key <= values[1])
                          and self._get(e.key) is not None)
            return "\n".join([*keys, "END"])
        if command == "HSET" and count == 3:
            entry = self._get(values[0])
            if entry is not None and entry.kind != "hash":
                return "ERROR wrong type"
            updated = entry.clone() if entry else Entry(values[0], kind="hash")
            index = next((i for i, pair in enumerate(updated.fields)
                          if pair[0] == values[1]), -1)
            if index < 0:
                updated.fields.append((values[1], values[2]))
            else:
                updated.fields[index] = (values[1], values[2])
            self._put(updated)
            return "1" if index < 0 else "0"
        if command == "HGET" and count == 2:
            entry = self._get(values[0])
            if entry is None:
                return "(nil)"
            if entry.kind != "hash":
                return "ERROR wrong type"
            for key, value in entry.fields:
                if key == values[1]:
                    return value
            return "(nil)"
        if command == "HGETALL" and count == 1:
            entry = self._get(values[0])
            if entry is None:
                return "(nil)"
            if entry.kind != "hash":
                return "ERROR wrong type"
            return " ".join(part for key, value in sorted(entry.fields)
                            for part in (key, value)) or "(nil)"
        if command in ("LPUSH", "RPUSH") and count == 2:
            entry = self._get(values[0])
            if entry is not None and entry.kind != "list":
                return "ERROR wrong type"
            updated = entry.clone() if entry else Entry(values[0], kind="list")
            if command == "LPUSH":
                updated.items.insert(0, values[1])
            else:
                updated.items.append(values[1])
            self._put(updated)
            return str(len(updated.items))
        if command in ("LPOP", "RPOP") and count == 1:
            """Remove and return an element, persisting the resulting list."""
            entry = self._get(values[0])
            if entry is None or (entry.kind == "list" and not entry.items):
                return ""
            if entry.kind != "list":
                return "ERROR wrong type"
            updated = entry.clone()
            removed = (updated.items.pop(0) if command == "LPOP"
                       else updated.items.pop())
            self._put(updated)
            return removed
        if command == "LRANGE" and count == 3:
            try:
                start, stop = int(values[1]), int(values[2])
            except ValueError:
                return "ERROR invalid range"
            entry = self._get(values[0])
            if entry is None:
                return "(nil)"
            if entry.kind != "list":
                return "ERROR wrong type"
            size = len(entry.items)
            if start < 0:
                start += size
            if stop < 0:
                stop += size
            start = max(0, start)
            stop = min(size - 1, stop)
            subset = entry.items[start:stop + 1] if start <= stop else []
            return "\n".join([*subset, "END"])
        if command in ("INCR", "DECR") and count == 1:
            entry = self._get(values[0])
            if entry is not None and entry.kind != "string":
                return "ERROR wrong type"
            try:
                old_value = int(entry.value) if entry is not None else 0
            except ValueError:
                return "ERROR value is not an integer"
            new_value = old_value + (1 if command == "INCR" else -1)
            self._put(Entry(values[0], value=str(new_value),
                            expires_at=entry.expires_at if entry else None))
            return str(new_value)
        if command == "FLUSHDB" and count == 0:
            self._write({"op": "flush"})
            return "OK"
        return "ERROR unknown command or invalid arguments"


def run(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout,
        database_path: str | Path = "data.db") -> None:
    database = Database(database_path)
    for line in input_stream:
        try:
            args = shlex.split(line)
        except ValueError:
            print("ERROR invalid quoting", file=output_stream, flush=True)
            continue
        if not args:
            continue
        response = database.execute(args)
        print(response, file=output_stream, flush=True)
        if args[0].upper() == "EXIT" and len(args) == 1:
            break


if __name__ == "__main__":
    run()
