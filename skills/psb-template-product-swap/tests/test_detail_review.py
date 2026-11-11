import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_sku import detail_review


class DetailReviewTests(unittest.TestCase):
    def test_angled_sku_native_size_is_insufficient(self):
        review = detail_review((803, 430), (1124, 602), False)
        self.assertEqual(review['status'], 'native-detail-insufficient')
        self.assertEqual(review['input_to_placement_scale'], 1.4)

    def test_dimensions_are_not_visual_acceptance(self):
        review = detail_review((1714, 918), (1124, 602), False)
        self.assertEqual(review['status'], 'visual-review-required')

    def test_ai_preview_not_promoted_for_sufficient_dimensions(self):
        review = detail_review((1714, 918), (1124, 602), True)
        self.assertEqual(review['status'], 'ai-restored-preview-only')


if __name__ == '__main__':
    unittest.main()
