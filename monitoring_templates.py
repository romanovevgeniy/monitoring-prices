"""Шаблоны меняют сценарий запуска, сохраняя конфигурацию прежних магазинов."""
TV_SPB = 'tv-spb'
TEMPLATES = {'all': 'Все магазины', TV_SPB: 'samsungstore · Санкт-Петербург'}


def apply_template(table, template='all'):
    if template not in TEMPLATES:
        raise ValueError(f'Неизвестный шаблон: {template}')
    if table.get('source_template') == TV_SPB:
        template = TV_SPB
    if template == TV_SPB:
        if table['name'] != 'ТВ':
            raise ValueError('Шаблон samsungstore СПБ предназначен только для ТВ')
        return dict(table, template=template, price_cols={'samsungstore': (table['price_cols'].get('mvideo') or table['price_cols'].get('samsungstore'))}, region='Санкт-Петербург')
    return dict(table, template='all')
