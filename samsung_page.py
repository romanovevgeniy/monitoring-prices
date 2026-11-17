"""Чтение JSON samsungstore: прежний Next.js и новый серверный Flight-поток.

JavaScript не исполняется. Регион проверяется по выбранному currentRegion,
а не по упоминанию СПБ в списке доступных городов или заголовке страницы.
"""
import json
import re
from html.parser import HTMLParser
from stores import StoreError


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active=False;self.parts=[];self.scripts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script':
            attributes=dict(attrs)
            self.active=attributes.get('type','').lower() in ('','text/javascript','application/javascript')
            self.parts=[]
    def handle_data(self,data):
        if self.active:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.scripts.append(''.join(self.parts));self.active=False


def flight_records(html):
    parser=Scripts();parser.feed(html)
    chunks=[];decoder=json.JSONDecoder()
    for script in parser.scripts:
        match=re.match(r'\s*self\.__next_f\.push\(',script)
        if not match:continue
        packet,_=decoder.raw_decode(script,match.end())
        if isinstance(packet,list) and len(packet)==2 and packet[0]==1 and isinstance(packet[1],str):
            chunks.append(packet[1])
    if not chunks:raise ValueError('нет серверных данных страницы')
    stream=''.join(chunks).encode('utf-8');offset=0;records={}
    while offset<len(stream):
        if stream[offset:offset+1] in (b'\n',b'\r'):
            offset+=1;continue
        match=re.match(rb'([0-9a-f]*):',stream[offset:])
        if not match:raise ValueError('неизвестная запись серверных данных')
        key=match[1].decode();offset+=match.end()
        # Текстовые записи могут содержать переводы строк и псевдо-JSON.
        # Их длина задана в UTF-8 байтах; искать следующий id внутри текста нельзя.
        if stream[offset:offset+1]==b'T':
            length=re.match(rb'T([0-9a-f]+),',stream[offset:])
            if not length:raise ValueError('неполная текстовая запись')
            offset+=length.end()+int(length[1],16)
            if offset>len(stream):raise ValueError('обрезана текстовая запись')
            continue
        end=stream.find(b'\n',offset)
        if end<0:raise ValueError('обрезаны серверные данные')
        payload=stream[offset:end];offset=end+1
        try:value=json.loads(payload)
        except ValueError:continue  # модули I, ссылки HL и прочие не-JSON записи
        if key in records and records[key]!=value:raise ValueError('конфликт серверных данных')
        records[key]=value
    return records


def objects(value):
    stack=[value]
    while stack:
        item=stack.pop()
        if isinstance(item,dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item,list):stack.extend(item)


def resolve(value,records):
    if not isinstance(value,str):return value
    match=re.fullmatch(r'\$([0-9a-f]+)((?::[^:]+)*)',value)
    if not match:raise ValueError('неизвестная ссылка на регион')
    result=records[match[1]]
    for part in match[2].split(':')[1:]:
        if part=='props' and isinstance(result,list) and len(result)==4 and result[0]=='$':result=result[3]
        elif isinstance(result,list):result=result[int(part)]
        else:result=result[part]
    return result


def same_value(values,name):
    if not values or any(value!=values[0] for value in values[1:]):
        raise ValueError('нет однозначных данных: '+name)
    return values[0]


def page_data(html):
    legacy=re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',html,re.S)
    try:
        if legacy:
            data=json.loads(legacy[1])
            region=data['props']['props']['currentRegion']['REGION_CODE']
            result=data['props']['pageProps']
        else:
            records=flight_records(html)
            nodes=[node for value in records.values() for node in objects(value)]
            regions=[resolve(node['currentRegion'],records)['REGION_CODE'] for node in nodes if 'currentRegion' in node]
            region=same_value(regions,'currentRegion')
            result={}
            catalogs=[node['initialProductsData'] for node in nodes if 'initialProductsData' in node]
            if catalogs:result['initialProductsData']=same_value(catalogs,'каталог')
            products=[]
            for node in nodes:
                state=node.get('dehydratedState')
                if not isinstance(state,dict):continue
                for query in state.get('queries',[]):
                    key=query.get('queryKey') if isinstance(query,dict) else None
                    if isinstance(key,list) and len(key)==2 and key[0]=='product':
                        if query.get('state',{}).get('status')!='success':raise ValueError('товар не загружен')
                        products.append(query['state']['data'])
            if products:result['product']=same_value(products,'карточка товара')
            if not result:raise ValueError('нет каталога или карточки товара')
        if region!='spb':
            raise StoreError(f'неверный регион samsungstore: {region}; требуется Санкт-Петербург')
        return result
    except (KeyError,IndexError,TypeError,ValueError,RecursionError) as error:
        raise StoreError('Не удалось прочитать данные samsungstore: изменён или неполон формат страницы. Регион СПБ не подтверждён.') from error
