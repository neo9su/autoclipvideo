import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("recover", Path(__file__).resolve().parents[1] / "scripts/recover_product_links.py")
recover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recover)


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"; con = sqlite3.connect(self.db)
        con.executescript("""CREATE TABLE products(id INTEGER PRIMARY KEY, product_id TEXT, product_name TEXT, product_url TEXT, enabled INTEGER, store_name TEXT, link_meta TEXT);
        CREATE TABLE publish_tasks(id INTEGER PRIMARY KEY, status TEXT, product_id INTEGER, product_ids TEXT);
        INSERT INTO products VALUES(1,'dom_x','same name','',1,'shop','{"shop_id":"5"}');""")
        con.commit(); con.close()
        self.manifest = self.root / "plan.json"
        self.manifest.write_text(json.dumps({"candidates":[{"catalogue_id":1,"records":[
            {"product_id":"101","detail_url":"https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=101","shop_name":"shop"},
            {"product_id":"102","detail_url":"https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=102","shop_name":"shop"}]}]}))
        self.journal = self.root / "journal.json"; self.backup = self.root / "backup.db"

    def tearDown(self): self.tmp.cleanup()

    def test_apply_and_conditional_rollback(self):
        result = recover.apply(self.db, self.manifest, self.journal, self.backup)
        self.assertEqual(len(result["inserted_ids"]), 2)
        con=sqlite3.connect(self.db); rows=con.execute("SELECT product_id,enabled FROM products ORDER BY id").fetchall(); con.close()
        self.assertEqual(rows, [('dom_x',0),('101',1),('102',1)])
        self.assertEqual(recover.rollback(self.db,self.journal)["rolled_back"],2)
        con=sqlite3.connect(self.db); rows=con.execute("SELECT product_id,enabled FROM products").fetchall(); con.close()
        self.assertEqual(rows,[('dom_x',1)])

    def test_active_publish_blocks_changes(self):
        con=sqlite3.connect(self.db);con.execute("INSERT INTO publish_tasks VALUES(9,'publishing',NULL,NULL)");con.commit();con.close()
        with self.assertRaisesRegex(RuntimeError,"affected active publish"):
            recover.apply(self.db,self.manifest,self.journal,self.backup)
        self.assertFalse(self.backup.exists())

    def test_unrelated_pending_task_does_not_block(self):
        con=sqlite3.connect(self.db);con.execute("INSERT INTO publish_tasks VALUES(9,'pending',77,'77,78')");con.commit();con.close()
        self.assertEqual(recover.apply(self.db,self.manifest,self.journal,self.backup)["insert_count"],2)


if __name__ == '__main__': unittest.main()
