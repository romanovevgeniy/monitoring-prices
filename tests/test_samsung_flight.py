import json
import unittest
import httpx
from samsung_tv import page_data, SamsungTV
from stores import StoreError


def modern(data,region='spb',split=False):
    layout=['$','$L1',None,{'allRegions':[{'REGION_CODE':'spb'},{'REGION_CODE':'moscow'}],
                           'currentRegion':'$19:props:allRegions:'+('0' if region=='spb' else '1')}]
    text=':HL["/style.css","style"]\n19:'+json.dumps(layout,ensure_ascii=False)+'\n'
    description='Описание\nтовара\n</p>'
    text+='a:T'+format(len(description.encode()),'x')+','+description
    text+='12:'+json.dumps(['$','$L2',None,data],ensure_ascii=False)+'\n'
    parts=[text[:len(text)//2],text[len(text)//2:]] if split else [text]
    return ''.join('<script>self.__next_f.push('+json.dumps([1,p],ensure_ascii=False)+')</script>' for p in parts)


class FlightTests(unittest.TestCase):
    def test_region_reference_and_text_frame_split_across_chunks(self):
        data=page_data(modern({'initialProductsData':{'TOTAL':1,'ITEMS':[]}},split=True))
        self.assertEqual(data['initialProductsData']['TOTAL'],1)

    def test_spb_in_all_regions_does_not_confirm_moscow(self):
        with self.assertRaisesRegex(StoreError,'регион'):
            page_data(modern({'initialProductsData':{}},region='moscow'))

    def test_missing_active_region_rejected(self):
        html='<script>self.__next_f.push('+json.dumps([1,'1:'+json.dumps({'allRegions':[{'REGION_CODE':'spb'}],'initialProductsData':{}})+'\n'])+')</script>'
        with self.assertRaises(StoreError):page_data(html)

    def test_product_query_is_not_confused_with_crosslinks(self):
        data={'dehydratedState':{'queries':[
            {'queryKey':['product','1','crosslinks'],'state':{'status':'success','data':{'ARTICLE':'WRONG'}}},
            {'queryKey':['product','1'],'state':{'status':'success','data':{'ARTICLE':'RIGHT'}}}]}}
        self.assertEqual(page_data(modern(data))['product']['ARTICLE'],'RIGHT')

    def test_truncated_stream_is_error(self):
        with self.assertRaises(StoreError):page_data(modern({'initialProductsData':{}})[:-40])


class ModernCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_catalog_pagination_and_exact_product(self):
        def response(r):
            if '/catalog/' in r.url.path:
                n=int(r.url.params.get('page','1'))
                return httpx.Response(200,text=modern({'initialProductsData':{'TOTAL':2,'LAST_PAGE':2,'CURRENT_PAGE':n,'ITEMS':[{'KOD':str(n),'TITLE':'TV'}]}}))
            code=r.url.path.split('productID')[1].strip('/')
            product={'ARTICLE':'EXACT' if code=='2' else 'OTHER','KOD':code,'PRICE':{'VALUE':99,'PRICE_TYPE':'spb_special'},'ORDER_TYPE':'ORDER','VISIBLE_PRICE':True}
            return httpx.Response(200,text=modern({'dehydratedState':{'queries':[{'queryKey':['product',code],'state':{'status':'success','data':product}}]}}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            result=await SamsungTV(client).find('EXACT')
            self.assertEqual(result.price,99);self.assertIn('productID2',result.url)
