import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("link_audit", Path(__file__).resolve().parents[1] / "scripts/audit_product_link_candidates.py")
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


class LinkCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.product = dict(id=1, product_id="dom_placeholder", product_name="exact style",
                            product_url="", store_name="shop", link_meta='{"shop_id":"5"}')
        self.row = dict(name="exact style", product_id="1234567890123456789", shop_id="5",
                        shop_name="shop", detail_url="https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=1234567890123456789")

    def test_scoped_candidate_preserves_original_identity(self):
        result = audit_module.audit([self.product], [self.row])["candidates"][0]
        self.assertEqual(result["status"], "single_link_candidate")
        self.assertEqual(result["link_option_count"], 1)
        self.assertEqual(result["expected_before"]["product_id"], "dom_placeholder")
        self.assertFalse(result["cart_acceptance_validated"])

    def test_same_name_other_shop_rejected(self):
        self.row["shop_id"] = "6"
        self.assertEqual(audit_module.audit([self.product], [self.row])["candidates"], [])

    def test_unscoped_or_mismatched_link_rejected(self):
        self.assertFalse(audit_module.valid_record(dict(self.row, unscoped=True)))
        self.assertFalse(audit_module.valid_record(dict(self.row, product_id="2")))
        self.assertFalse(audit_module.valid_record(dict(self.row, detail_url=self.row["detail_url"].replace("haohuo.jinritemai.com", "example.org"))))

    def test_same_name_multiple_links_are_preserved_as_options(self):
        other = dict(self.row, product_id="2", detail_url=self.row["detail_url"].replace("1234567890123456789", "2"))
        result = audit_module.audit([self.product], [self.row, other])["candidates"][0]
        self.assertEqual(result["status"], "multiple_link_candidates")
        self.assertEqual(result["link_option_count"], 2)
        self.assertEqual(result["records"], [self.row, other])

    def test_existing_link_and_missing_shop_metadata_untouched(self):
        self.assertEqual(audit_module.audit([dict(self.product, product_url="existing")], [self.row])["candidates"], [])
        self.assertEqual(audit_module.audit([dict(self.product, enabled=0)], [self.row])["candidates"], [])
        self.assertEqual(audit_module.audit([dict(self.product, link_meta="[]")], [self.row])["candidates"], [])


if __name__ == "__main__":
    unittest.main()
