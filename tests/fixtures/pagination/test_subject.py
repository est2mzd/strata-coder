import unittest
from subject import pages
class PagesTests(unittest.TestCase):
 def test_all_items(self):self.assertEqual(pages([1,2,3,4,5],2),[[1,2],[3,4],[5]])
 def test_exact(self):self.assertEqual(pages([1,2,3,4],2),[[1,2],[3,4]])
 def test_empty(self):self.assertEqual(pages([],2),[])
 def test_invalid(self):
  for size in (0,-1):
   with self.assertRaises(ValueError):pages([1],size)
