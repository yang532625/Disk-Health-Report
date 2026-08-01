import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para treemap_layout."""

import unittest

from treemap_layout import layout_treemap


class TestTreemapLayout(unittest.TestCase):
    def test_empty(self):
        rects, indices = layout_treemap([])
        self.assertEqual(rects, [])
        self.assertEqual(indices, [])

    def test_single_item(self):
        rects, indices = layout_treemap([100])
        self.assertEqual(len(rects), 1)
        self.assertAlmostEqual(rects[0].w * rects[0].h, 1.0, places=2)

    def test_area_sum_approx_one(self):
        sizes = [1000, 500, 200, 100, 50]
        rects, _ = layout_treemap(sizes)
        total_area = sum(r.w * r.h for r in rects)
        self.assertAlmostEqual(total_area, 1.0, places=2)

    def test_other_bucket_when_many_items(self):
        sizes = list(range(1, 60))
        rects, indices = layout_treemap(sizes, max_items=48)
        self.assertIn(-1, indices)
        self.assertGreater(len(rects), 0)


if __name__ == "__main__":
    unittest.main()
