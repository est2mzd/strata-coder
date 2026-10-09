import copy
import unittest
from query import parse_page, parse_size
from pagination import paginate
from service import list_catalog

class QueryTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(parse_page(None),1)
        self.assertEqual(parse_size(None),10)
    def test_decimal_strings(self):
        self.assertEqual(parse_page(' 2 '),2)
        self.assertEqual(parse_size('03'),3)
    def test_page_invalid(self):
        for value in (0,-1,True,False,1.5,'1.5','x','','+1','١'):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_page(value)
    def test_size_invalid(self):
        for value in (0,-1,True,False,1.5,'1.5','x','','+1','١'):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_size(value)
    def test_size_cap(self):self.assertEqual(parse_size('999'),50)

class PaginationTests(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate([1,2,3],1,2),{'items':[1,2],'total':3,'has_next':True})
    def test_exact_last(self):
        self.assertEqual(paginate([1,2,3,4],2,2),{'items':[3,4],'total':4,'has_next':False})
    def test_partial_and_beyond(self):
        self.assertEqual(paginate([1,2,3],2,2)['items'],[3])
        self.assertEqual(paginate([1],8,2),{'items':[],'total':1,'has_next':False})
    def test_empty(self):self.assertEqual(paginate([],1,2),{'items':[],'total':0,'has_next':False})
    def test_invalid_arguments(self):
        for page,size in ((0,2),(1,0),(-1,2),(1,-1),(True,2),(1,1.5)):
            with self.subTest(page=page,size=size),self.assertRaises(ValueError):paginate([],page,size)

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.records=[{'id':4},{'id':1,'active':False},{'id':3},{'id':2}]
    def test_filter_before_paging_and_total(self):
        self.assertEqual(list_catalog(self.records,{'size':'2'}),
            {'items':[{'id':2},{'id':3}],'total':3,'has_next':True})
    def test_second_page(self):
        self.assertEqual(list_catalog(self.records,{'page':'2','size':'2'}),
            {'items':[{'id':4}],'total':3,'has_next':False})
    def test_no_mutation(self):
        before=copy.deepcopy(self.records);params={'size':'2'};old=dict(params)
        list_catalog(self.records,params)
        self.assertEqual(self.records,before);self.assertEqual(params,old)
    def test_all_inactive(self):
        self.assertEqual(list_catalog([{'id':1,'active':False}],{}),
            {'items':[],'total':0,'has_next':False})
    def test_invalid_query_propagates(self):
        with self.assertRaises(ValueError):list_catalog(self.records,{'page':'bad'})
