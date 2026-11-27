# Append-Only Key-Value Store

A Python 3.10+ terminal database using a **linear-scan list index** rather than a built-in dictionary/map for storage. Changes are saved as JSON-lines operations to `data.db`, flushed and `fsync`ed for durability. At startup, the program replays the log. Transactions stage changes in memory and commit as one log record.

## Run

```bash
python3 kvstore.py
```

Or pipe commands in for an automated test:

```bash
printf 'SET name Ada\nGET name\nEXIT\n' | python3 kvstore.py
```

The database file is created in the **current working directory**. To reset, use `FLUSHDB` or remove `data.db` with the program stopped.

## Commands

| Command | Example | Output convention |
|---|---|---|
| SET | `SET city Denton` | `OK` |
| GET | `GET city` | value or blank line |
| DEL | `DEL city` | `1` if removed, else `0` |
| EXISTS | `EXISTS city` | `1` or `0` |
| MSET | `MSET a 1 b 2` | `OK` |
| MGET | `MGET a b missing` | one value per line, blank line for absent keys |
| EXPIRE | `EXPIRE a 60` | `1` if key existed, else `0` |
| TTL | `TTL a` | remaining seconds; `-1` no expiry, `-2` missing |
| RANGE | `RANGE a z` | one key per line, terminated by `END` (inclusive bounds) |
| BEGIN | `BEGIN` | `OK` |
| COMMIT | `COMMIT` | `OK` |
| ABORT | `ABORT` | `OK` |
| HSET | `HSET user name Ada` | `1` new field, `0` updated |
| HGET | `HGET user name` | value or `(nil)` |
| HGETALL | `HGETALL user` | space-separated field/value pairs, sorted by field |
| LPUSH | `LPUSH queue first` | length |
| RPUSH | `RPUSH queue second` | length |
| LRANGE | `LRANGE queue 0 -1` | one value per line followed by `END`; inclusive stop, negative indexes supported |
| INCR | `INCR n` | incremented integer |
| DECR | `DECR n` | decremented integer |
| FLUSHDB | `FLUSHDB` | `OK` |
| EXIT | `EXIT` | `BYE` and exits |

Use double quotes for arguments with spaces, e.g. `SET greeting "hello world"`. Invalid commands return `ERROR ...`. Keys are case-sensitive; command names are case-insensitive.

**Gradebot note:** The assignment does not state exact output strings for missing keys, collections, transactions or EXIT. This project uses documented Redis-style conventions. If Gradebot expects another format, adapt `Database.execute` outputs to its specification after running the grader.

## Tests and lint

```bash
python3 -m unittest discover -s tests -v
python3 -m pip install ruff
ruff check .
```

GitHub Actions runs tests and lint on pushes and pull requests.

## Git and submission

```bash
git init
git add .
git commit -m "Implement persistent append-only key-value store"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

Create a **public** GitHub repository before adding its remote. Run Gradebot with working directory set to the repository root and command `python3 kvstore.py`. Capture its rubric screenshot with your identifying information visible, save as `gradebot_screenshot.png` in the project root, then commit and push the screenshot. **Create the required final tag after the screenshot commit**:

```bash
git add gradebot_screenshot.png
git commit -m "Add Gradebot rubric screenshot"
git tag project
git push origin main
git push origin project
```

Do not fabricate a Gradebot screenshot; take it from the actual grader results.

## Gradebot format compatibility

Gradebot expects missing `GET` to produce an empty line, `MGET` values on separate lines, and `RANGE`/`LRANGE` as newline-delimited results terminated with `END`. This build includes those adjustments.
