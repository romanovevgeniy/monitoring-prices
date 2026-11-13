"""Метаданные проверок вне Excel: свежесть, точный повтор и понятные ошибки."""
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timedelta


def failure_message(detail):
    text=str(detail); lowered=text.lower()
    rules=[
        (('permissionerror','access denied','permission denied','winerror 32'), 'file_access', 'Не удалось записать файл.', 'Закройте таблицу в других программах и проверьте права на папку.'),
        (('регион','санкт-петербург','spb_'), 'region', 'Сайт не подтвердил цену Санкт-Петербурга.', 'Повторите проверку позже. Цена другого города не используется.'),
        (('другой товар','артикул','модель'), 'product', 'Не удалось подтвердить нужный товар.', 'Проверьте полный артикул и ссылку на карточку.'),
        (('timeout','таймаут','превышено время'), 'timeout', 'Сайт не ответил вовремя.', 'Повторите ошибочные позиции позже и проверьте подключение к интернету.'),
        (('антибот','captcha','403','429'), 'blocked', 'Сайт ограничил доступ.', 'Если открылась проверка в Chrome, пройдите её и повторите сбор позже.'),
        (('таблица изменена','файл измен','исходный файл измен'), 'conflict', 'Файл был изменён другой программой.', 'Перечитайте таблицу перед сохранением.'),
        (('chrome','browser executable'), 'browser', 'Не удалось открыть браузер.', 'Проверьте установку Google Chrome и повторите запуск.'),
        (('http','connect','network','dns'), 'network', 'Не удалось получить данные сайта.', 'Проверьте интернет и повторите ошибочные позиции позже.'),
        (('no space','disk full','места на диске'), 'disk', 'Не хватает места для сохранения.', 'Освободите место в папке результатов и повторите сбор.'),
    ]
    for words,code,message,action in rules:
        if any(word in lowered for word in words):
            return dict(code=code,message=message,action=action,detail=text)
    return dict(code='operation',message='Не удалось завершить операцию.',
                action='Проверьте сообщение в журнале и настройки выбранной таблицы.',detail=text)


def report_path(book):
    return Path(str(book)+'.monitoring.json')


def read_report(book):
    try:
        path=report_path(book)
        if path.stat().st_size>20_000_000:return {}
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('records'),list):return {}
        if len(data['records'])>100000:return {}
        seen=set()
        for record in data['records']:
            if not isinstance(record,dict):return {}
            key=(record.get('article'),record.get('store'))
            if not all(isinstance(x,str) and x for x in key) or key in seen:return {}
            if record.get('status') not in ('ok','missing','error','pending'):return {}
            seen.add(key)
        return data
    except (OSError,ValueError,TypeError):
        return {}


def save_report(book,table,template,source,records):
    data=dict(schema=1,table=table,template=template,source=str(Path(source).resolve()),records=records)
    destination=report_path(book)
    fd,name=tempfile.mkstemp(prefix='.'+destination.name,suffix='.tmp',dir=destination.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,allow_nan=False)
        os.replace(name,destination)
    finally:
        Path(name).unlink(missing_ok=True)
    return data


def record_index(data,table,template):
    if data.get('table')!=table or data.get('template')!=template:return {}
    return {(r['article'],r['store']):r for r in data.get('records',[])}


def cell_status(record,value,now=None):
    now=now or datetime.now().astimezone()
    unknown=dict(code='unchecked',label='Не проверено',checkedAt='',message='Нет подтверждения актуальности этой цены.')
    if not record or record.get('value')!=value:return unknown
    stamp=record.get('checkedAt') or ''
    if record['status']=='error':
        error=failure_message(record.get('note',''))
        return dict(code='error',label='Ошибка · прежняя цена',checkedAt=record.get('verifiedAt') or '',
                    message=error['message']+' '+error['action'])
    if record['status']=='pending':
        return dict(code='pending',label='Не обработано',checkedAt=record.get('verifiedAt') or '',message='В этом запуске цена не проверена.')
    try:
        checked=datetime.fromisoformat(stamp)
        if checked.tzinfo is None or checked>now+timedelta(minutes=5):return unknown
        today=checked.astimezone(now.tzinfo).date()==now.date()
    except (TypeError,ValueError):return unknown
    if not today:
        return dict(code='stale',label='Прежняя · '+checked.astimezone(now.tzinfo).strftime('%d.%m.%Y'),checkedAt=stamp,message='Цена подтверждена ранее; сегодня не проверена.')
    missing=record['status']=='missing'
    return dict(code='unavailable' if missing else 'fresh',label='Сегодня · нет в наличии' if missing else 'Обновлено сегодня',checkedAt=stamp,message=record.get('note') or 'Цена подтверждена сегодня.')


def retry_pairs(book,source,template):
    data=read_report(book)
    if not data or data.get('source')!=str(Path(source).resolve()) or data.get('template')!=template:
        raise ValueError('Отчёт повтора не соответствует исходной таблице и шаблону. Запустите новый сбор.')
    pairs={(data['table'],r['article'],r['store']) for r in data['records'] if r['status']=='error'}
    if not pairs:raise ValueError('В отчёте нет ошибочных позиций для повтора.')
    return pairs


def comparison_summary(rows):
    updated=cheaper=errors=unconfirmed=0;maximum=0
    for row in rows:
        codes=[s['code'] for s in row['statuses']]
        updated+=bool(codes) and all(c in ('fresh','unavailable') for c in codes)
        errors+='error' in codes
        unconfirmed+=any(c not in ('fresh','unavailable') for c in codes)
        cheaper+=row['cheaper']
        maximum=max(maximum,row['difference'])
    return dict(total=len(rows),updated=updated,cheaper=cheaper,errors=errors,unconfirmed=unconfirmed,maxDifference=maximum)


def write_run_report(table,source,destination,jobs,outcomes,previous_source=None):
    """После успешной записи xlsx связываем проверки с артикулом и фактической ценой."""
    import openpyxl
    from excel import article_rows
    previous={}
    for path in [source,previous_source,destination]:
        if path:
            previous.update(record_index(read_report(path),table['name'],table['template']))
    attempted={(item[2],store) for store,items in jobs.items() for item in items if item[0]==table['name']}
    book=openpyxl.load_workbook(destination,data_only=True)
    records=[]
    try:
        for article,row in article_rows(book.active,table).items():
            for store,col in table['price_cols'].items():
                value=book.active[f'{col}{row}'].value
                key=(article,store);old=previous.get(key)
                if old and old.get('value')!=value:old=None
                outcome=outcomes.get((table['name'],article,store))
                if key in attempted:
                    outcome=outcome or dict(status='pending',note='Не обработано в этом запуске',checkedAt='')
                    verified=(outcome.get('checkedAt','') if outcome['status'] in ('ok','missing') else
                              (old.get('checkedAt','') if old and old['status'] in ('ok','missing') else (old or {}).get('verifiedAt','')))
                    records.append(dict(outcome,article=article,store=store,value=value,verifiedAt=verified))
                elif old:
                    records.append(old)
        return save_report(destination,table['name'],table['template'],source,records)
    finally:
        book.close()
