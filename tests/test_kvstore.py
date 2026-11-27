"""Black-box-style and persistence regression tests."""

import io
import tempfile
import unittest
from pathlib import Path

from kvstore import Database, run


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "data.db"
        self.db = Database(self.path)

    def command(self, text):
        return self.db.execute(text.split())

    def test_created_and_set_get_overwrite(self):
        self.assertTrue(self.path.exists())
        self.assertEqual(self.command("GET missing"), "")
        self.assertEqual(self.command("SET fruit apple"), "OK")
        self.assertEqual(self.command("SET fruit mango"), "OK")
        self.assertEqual(self.command("GET fruit"), "mango")
        self.assertGreater(self.path.stat().st_size, 0)
        self.assertEqual(Database(self.path).execute(["GET", "fruit"]), "mango")

    def test_delete_exists_and_multi(self):
        self.assertEqual(self.command("MSET a 1 b 2 c 3"), "OK")
        self.assertEqual(self.command("MGET a c z"), "1\n3\n")
        self.assertEqual(self.command("EXISTS b"), "1")
        self.assertEqual(self.command("DEL b"), "1")
        self.assertEqual(self.command("DEL b"), "0")
        self.assertEqual(Database(self.path).execute(["EXISTS", "b"]), "0")

    def test_expire_ttl_range(self):
        self.command("MSET apple 1 banana 2 cherry 3")
        self.assertEqual(self.command("RANGE apple cherry"), "apple\nbanana\ncherry\nEND")
        self.assertEqual(self.command("TTL apple"), "-1")
        self.assertEqual(self.command("TTL missing"), "-2")
        self.assertEqual(self.command("EXPIRE apple 20"), "1")
        self.assertIn(int(self.command("TTL apple")), (19, 20))
        self.assertEqual(self.command("EXPIRE banana 0"), "1")
        self.assertEqual(self.command("EXISTS banana"), "0")

    def test_transactions(self):
        self.command("SET a old")
        self.assertEqual(self.command("BEGIN"), "OK")
        self.command("SET a new")
        self.command("SET b value")
        self.assertEqual(self.command("GET a"), "new")
        self.assertEqual(Database(self.path).execute(["GET", "a"]), "old")
        self.command("ABORT")
        self.assertEqual(self.command("GET a"), "old")
        self.command("BEGIN")
        self.command("SET a new")
        self.command("COMMIT")
        self.assertEqual(Database(self.path).execute(["GET", "a"]), "new")

    def test_hash_list_counter_and_flush(self):
        self.assertEqual(self.command("HSET user name Ada"), "1")
        self.assertEqual(self.command("HSET user name Grace"), "0")
        self.assertEqual(self.command("HGET user name"), "Grace")
        self.assertEqual(self.command("HGETALL user"), "name Grace")
        self.command("LPUSH tasks second")
        self.command("LPUSH tasks first")
        self.command("RPUSH tasks third")
        self.assertEqual(self.command("LRANGE tasks 0 -1"), "first\nsecond\nthird\nEND")
        self.assertEqual(self.command("LRANGE tasks -2 -1"), "second\nthird\nEND")
        self.assertEqual(self.command("INCR score"), "1")
        self.assertEqual(self.command("DECR score"), "0")
        fresh = Database(self.path)
        self.assertEqual(fresh.execute(["HGET", "user", "name"]), "Grace")
        self.assertEqual(fresh.execute(["LRANGE", "tasks", "0", "-1"]),
                         "first\nsecond\nthird\nEND")
        self.assertEqual(fresh.execute(["GET", "score"]), "0")
        self.command("FLUSHDB")
        self.assertEqual(Database(self.path).execute(["EXISTS", "user"]), "0")

    def test_piped_cli(self):
        source = io.StringIO('SET greeting "hello world"\nGET greeting\nEXIT\nGET greeting\n')
        output = io.StringIO()
        run(source, output, self.path)
        self.assertEqual(output.getvalue(), "OK\nhello world\nBYE\n")


if __name__ == "__main__":
    unittest.main()
