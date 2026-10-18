import unittest
import importlib.util
from scripts.validation.review_wig_homophones import retrieve


@unittest.skipUnless(importlib.util.find_spec('pypinyin'), 'Install validation/requirements-phonetic.txt in an isolated environment')
class HomophoneReviewTests(unittest.TestCase):
    def test_homophones_keep_original_evidence_and_distinct_catalogue_ids(self):
        cues=[{'start_sec':1,'end_sec':2,'text':'这是虎破精灵'}]
        products=[{'id':i,'product_name':'小圆-琥珀精灵【免发网】长卷发'} for i in (1,2)]
        hits=retrieve(cues,products)
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['catalogue_ids'],[1,2])
        self.assertEqual(hits[0]['original_text'],'这是虎破精灵')
        self.assertFalse(hits[0]['current_assertion'])
        self.assertFalse(hits[0]['sku_verified'])
        self.assertEqual(cues[0]['text'],'这是虎破精灵')

    def test_exact_names_punctuation_and_nonhomophones_not_rewritten(self):
        products=[{'id':1,'product_name':'小圆-琥珀精灵【免发网】长卷发'}]
        for text in ('这是琥珀精灵','虎破，精灵','这是虎皮精灵'):
            self.assertEqual(retrieve([{'start_sec':1,'end_sec':2,'text':text}],products),[])
