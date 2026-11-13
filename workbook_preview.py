"""Общий JSON-предпросмотр и сохранение НОСИМО для Qt и SwiftUI."""
import argparse
import json
import sys

from config import STORES
from excel import article_rows, as_number
from excel_html import format_value
from monitoring_templates import apply_template, TV_SPB
from workbook_document import WorkbookDocument
from result_quality import read_report, record_index, cell_status, comparison_summary, report_path


def number_text(value):
    if value is None:
        return ''
    return str(value) if isinstance(value, (int, float)) or value == '-' else ''


def preview(path, template='all', stores=None):
    doc=WorkbookDocument(path,editable=False)
    try:
        if not doc.table:
            raise ValueError('Не удалось распознать таблицу мониторинга. Проверьте заголовки.')
        table=apply_template(doc.table,template)
        ws=doc.workbook.active
        keys=[s for s in table['price_cols'] if stores is None or s in stores]
        columns=[{'key':s,'name':'samsungstore · СПБ' if table['template']==TV_SPB else STORES[s]} for s in keys]
        records=record_index(read_report(path),table["name"],table["template"])
        rows=[]
        retry=[]
        for article,row in article_rows(ws,table).items():
            base_col=ws[f"{table['base_col']}{row}"].column
            base=doc.displayed_value(ws.title,row,base_col)
            prices,lower,statuses=[],[],[]
            difference=0
            for store in keys:
                col=table['price_cols'][store]
                cell=ws[f'{col}{row}']
                is_source_price=(table['template']!=TV_SPB or 'samsungstore' in str(ws[f'{col}1'].value).lower())
                value=doc.displayed_value(ws.title,row,cell.column) if is_source_price else None
                prices.append(format_value(value,cell.number_format) if value is not None else '—')
                price_n,base_n=as_number(value),as_number(base)
                lower.append(bool(base_n and price_n is not None and price_n<base_n))
                status=cell_status(records.get((article,store)),value) if is_source_price else cell_status(None,None)
                statuses.append(status)
                if status['code']=='error':retry.append({'article':article,'store':store})
                if status['code']=='fresh' and base_n and base_n>0 and price_n is not None:
                    difference=max(difference,base_n-price_n)
            rows.append({'row':row,'article':article,'base':number_text(base),
                         'baseDisplay':format_value(base,ws[f"{table['base_col']}{row}"].number_format) if as_number(base) is not None else number_text(base) or '—',
                         'prices':prices,'lower':lower,'statuses':statuses,'cheaper':difference>0,'difference':difference})
        return {'filename':doc.path.name,'table':table['name'],'template':table['template'],
                'fingerprint':doc.digest.hex(),'columns':columns,'rows':rows,'count':len(rows),
                'summary':comparison_summary(rows),'retryPairs':retry,'reportPath':str(report_path(path))}
    finally:
        doc.close()


def apply_prices(path, fingerprint, edits, template='all', stores=None):
    doc=WorkbookDocument(path)
    try:
        if not fingerprint or doc.digest.hex()!=fingerprint:
            raise ValueError('Исходная таблица изменена. Обновите предпросмотр перед сохранением.')
        if not doc.table or not isinstance(edits,list) or len(edits)>10000:
            raise ValueError('Некорректные изменения НОСИМО')
        ws=doc.workbook.active
        base_col=ws[f"{doc.table['base_col']}1"].column
        seen=set()
        for item in edits:
            row=item.get('row') if isinstance(item,dict) else None
            if type(row) is not int or row in seen:
                raise ValueError('Некорректная или повторная строка НОСИМО')
            seen.add(row)
            doc.set_value(ws.title,row,base_col,item.get('value',''))
        doc.save()
    finally:
        doc.close()
    return preview(path,template,stores)


def main():
    ap=argparse.ArgumentParser(description='Предпросмотр таблицы и правка НОСИМО')
    ap.add_argument('--file',required=True)
    ap.add_argument('--template',choices=['all',TV_SPB],default='all')
    ap.add_argument('--stores',help='магазины через запятую')
    ap.add_argument('--changes',help='JSON с fingerprint и массивом edits')
    args=ap.parse_args()
    try:
        stores=args.stores.split(',') if args.stores is not None else None
        if args.changes:
            data=json.loads(args.changes)
            result=apply_prices(args.file,data.get('fingerprint'),data.get('edits'),args.template,stores)
        else:
            result=preview(args.file,args.template,stores)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),flush=True)
        sys.exit(1)


if __name__=='__main__':
    main()
