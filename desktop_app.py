"""«Мониторинг цен» — приложение для Windows (Qt). На Mac работает тоже — так его и проверяем.

Запуск из исходников: .venv/bin/python desktop_app.py
В собранной программе скрипты выполняет отдельный консольный tools/monitoring-tools.exe (у оконного exe нет stdout).

Окно повторяет Mac-версию (SwiftUI): выбор таблицы, магазинов, папки результатов и файла ссылок; кнопки «Цены НОСИМО»,
«Заполнить автоматически», «Запустить»/«Остановить», «Справка»; прогресс по магазинам и лента результатов.
Скрипты сообщают о прогрессе строками «@@{json}» (флаг --json), остановка — через стоп-файл.
"""
import filecmp
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

TOOLS = {"run": "run", "fill_links": "fill_links", "nosimo": "nosimo", "make_links": "make_links_template"}


def run_tool_and_exit():
    """exe --tool <имя> [аргументы] — запасной путь, если рядом нет tools/monitoring-tools.exe."""
    name = sys.argv[2]
    sys.argv = [TOOLS[name]] + sys.argv[3:]
    runpy.run_module(TOOLS[name], run_name="__main__")
    sys.exit(0)


if len(sys.argv) > 2 and sys.argv[1] == "--tool":
    run_tool_and_exit()

from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPalette, QShortcut  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from paths import APP_DIR, FROZEN  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == "--selftest":  # проверка сборки: Qt загружается, окно создаётся
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    QApplication(sys.argv[:1])
    sys.exit(0)

APP_NAME = "Мониторинг цен"
FEED_LIMIT = 300
GREEN, ORANGE, RED, GRAY = "#2e9e4f", "#d9822b", "#d64545", "#8a8a8e"
STYLE = """
QWidget { color: #1d1d1f; }
QLabel, QCheckBox, QPushButton, QToolButton { color: #1d1d1f; }
QMainWindow, QWidget#root { background: #ffffff; }
QMenu { background: #ffffff; border: 1px solid #d0d0d5; }
QMenu::item { padding: 5px 18px; }
QMenu::item:selected { background: #e8efff; }
QTreeWidget, QTextEdit { background: #ffffff; color: #1d1d1f; }
QHeaderView::section { background: #f6f6f7; color: #6e6e73; border: none; padding: 4px; }
QCheckBox { spacing: 6px; }
QFrame#card { background: #f6f6f7; border: 1px solid #e3e3e6; border-radius: 12px; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#muted, QLabel#caption { color: #6e6e73; }
QLabel#caption { font-size: 11px; }
QLabel#percent { font-size: 40px; font-weight: 700; }
QLabel#badge { background: #dff3e5; color: #1d6b36; border-radius: 8px; padding: 1px 8px; font-weight: 600; }
QLabel#warn { color: #b8620f; }
QPushButton, QToolButton { padding: 6px 14px; border-radius: 7px; border: 1px solid #d0d0d5; background: #fbfbfc; }
QPushButton:hover, QToolButton:hover { background: #f0f0f3; }
QToolButton::menu-indicator { image: none; }
QPushButton:disabled, QToolButton:disabled, QCheckBox:disabled { color: #a0a0a5; }
QPushButton#primary { background: #2f6fed; color: #ffffff; border: none; font-weight: 600; }
QPushButton#primary:disabled { background: #a9c1f5; }
QPushButton#danger { color: #c62828; }
QProgressBar { border: none; background: #e6e6ea; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #2f6fed; border-radius: 4px; }
QTreeWidget { border: none; }
"""


# ---------- вспомогательное ----------

def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def label(text="", name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return w


def open_path(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_help():
    """Руководство пользователя — docs/guide.html рядом с программой, открывается в браузере."""
    guide = APP_DIR / "docs" / "guide.html"
    if guide.exists():
        open_path(guide)


def reveal(path):
    path = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        open_path(path.parent)


def short(path):
    p = str(path)
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


def fmt_price(v):
    return f"{v:,}".replace(",", " ") + " ₽" if isinstance(v, int) else "—"


def fmt_eta(sec):
    if sec is None:
        return "Оцениваю время…"
    if sec < 60:
        return "Осталось меньше минуты"
    m = (sec + 30) // 60
    return f"Осталось ~{m} мин" if m < 60 else f"Осталось ~{m // 60} ч {m % 60} мин"


def fmt_clock(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def tool_command(name, args):
    """Как запустить скрипт.
    Собранная программа: консольный tools/monitoring-tools(.exe) рядом с ней — у оконного exe нет stdout,
    и ответы скриптов (прогресс, тип таблицы) терялись бы. Из исходников: python script.py."""
    if FROZEN:
        exe = Path(sys.executable).parent / "tools" / ("monitoring-tools.exe" if sys.platform == "win32" else "monitoring-tools")
        if exe.exists():
            return str(exe), [name] + args
        return sys.executable, ["--tool", name] + args
    return sys.executable, [str(APP_DIR / f"{TOOLS[name]}.py")] + args


def child_env():
    return dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")


def no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def detect_table(path):
    """{"table": "ТВ", "stores": [{"key", "name"}, …]} или {} если формат не распознан."""
    program, args = tool_command("run", ["--detect", str(path)])
    try:
        out = subprocess.run([program] + args, cwd=str(APP_DIR), capture_output=True, timeout=60,
                             env=child_env(), **no_window())
        return json.loads(out.stdout.decode("utf-8") or "{}")
    except Exception:
        return {}


class PathLabel(QLabel):
    """Путь, сокращённый посередине под ширину метки; полный — во всплывающей подсказке."""

    def __init__(self, name="caption"):
        super().__init__()
        self.setObjectName(name)
        self.full = ""
        self.setMinimumWidth(50)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_path(self, text):
        self.full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self.full, Qt.ElideMiddle, max(self.width(), 50)))


# ---------- окно ----------

class StoreRow:
    def __init__(self, grid, row, name, total):
        self.name, self.total, self.ok, self.missing, self.errors = name, total, 0, 0, 0
        self.title = QLabel(name)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximum(max(total, 1))
        self.count = QLabel()
        self.count.setObjectName("muted")
        self.labels = [QLabel() for _ in range(3)]
        for col, w in enumerate([self.title, self.bar, self.count] + self.labels):
            grid.addWidget(w, row, col)
        self.update()

    def add(self, status, retry=False):
        if retry:  # повтор в конце прогона: прежняя ошибка стала ценой или «нет»
            self.errors -= 1
        if status == "ok":
            self.ok += 1
        elif status == "ошибка":
            self.errors += 1
        else:
            self.missing += 1
        self.update()

    def update(self):
        done = self.ok + self.missing + self.errors
        self.bar.setValue(done)
        self.count.setText(f"{done}/{self.total}")
        for lab, (n, sym, color, tip) in zip(self.labels, [
            (self.ok, "✓", GREEN, "Найдено"), (self.missing, "–", GRAY, "Нет в наличии"),
            (self.errors, "⚠", ORANGE, "Ошибка")]):
            lab.setText(f"<span style='color:{color}'>{sym}</span> {n}")
            lab.setToolTip(tip)
            lab.setEnabled(n > 0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.setWindowTitle(APP_NAME)
        self.resize(900, 860)
        self.setMinimumSize(820, 680)
        self.setAcceptDrops(True)

        self.source = self._path_setting("sourceFile", must_exist=True)
        self.table_type = None
        # Основная папка: «Ссылки» (links_tv.xlsx, links_smart.xlsx) и папки дней «2026-10-22»
        # (ТВ, Смартфоны, Ссылки, Скриншоты, Логи). Спрашивается при первом запуске.
        self.root = self._path_setting("rootDirectory")
        self.process = None
        self.mode = "prices"
        self.phase = "idle"
        self.stop_file = None
        self.store_checks = {}
        self.reset_state()

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)
        lay.addLayout(self._header())
        lay.addWidget(self._setup_card())
        self.idle_card = self._idle_card()
        lay.addWidget(self.idle_card)
        self.progress_card = self._progress_card()
        lay.addWidget(self.progress_card)
        self.result_card = self._result_card()
        lay.addWidget(self.result_card)
        self.stores_card = card()
        self.stores_grid = QGridLayout(self.stores_card)
        self.stores_grid.setColumnStretch(1, 1)
        lay.addWidget(self.stores_card)
        lay.addWidget(self._feed_card(), 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        if self.source:
            self.set_source(self.source)
        self.refresh()

    # --- настройки ---

    def _path_setting(self, key, must_exist=False):
        v = self.settings.value(key)
        if not v:
            return None
        p = Path(v)
        return p if (not must_exist or p.exists()) else None

    def effective_links(self):
        """Файл ссылок выбранной таблицы в «Ссылки» основной папки (создаётся или переносится при запуске)."""
        if not self.root:
            return None
        return self.root / "Ссылки" / ("links_tv.xlsx" if self.table_type == "ТВ" else "links_smart.xlsx")

    def reset_state(self):
        self.total = self.done = 0
        self.eta = None
        self.started = self.finished = None
        self.stores = {}
        self.saved, self.screenshots, self.log_file = [], [], None
        self.errors = self.changed = 0
        self.missing_links, self.notices, self.tail = [], [], []
        self.crashed = False
        self.fail_message = ""
        self.antibot, self.retry_note = [], ""

    # --- построение интерфейса ---

    def _header(self):
        h = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(52, 52))
        h.addWidget(icon)
        v = QVBoxLayout()
        v.addWidget(label(APP_NAME, "title"))
        v.addWidget(label("М.Видео · DNS · МТС · samsungstore · Ozon · WB · Москва", "muted"))
        h.addLayout(v, 1)
        help_btn = QPushButton("?  Справка")
        help_btn.setToolTip("Руководство пользователя (F1)")
        help_btn.clicked.connect(open_help)
        h.addWidget(help_btn)
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=open_help)
        self.nosimo_btn = QPushButton("🏷  Цены НОСИМО")
        self.nosimo_btn.setToolTip("Заполнить колонку НОСИМО ценами с galaxystore.ru")
        self.nosimo_btn.clicked.connect(self.update_nosimo)
        h.addWidget(self.nosimo_btn)
        self.start_btn = QPushButton("▶  Запустить")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumWidth(150)
        self.start_btn.clicked.connect(self.start_or_stop)
        h.addWidget(self.start_btn)
        return h

    def _setup_card(self):
        c = card()
        g = QGridLayout(c)
        g.setColumnStretch(1, 1)
        g.setHorizontalSpacing(12)

        g.addWidget(label("Таблица", "muted"), 0, 0)
        src = QVBoxLayout()
        top = QHBoxLayout()
        self.source_name = label()
        self.badge = label("", "badge")
        top.addWidget(self.source_name)
        top.addWidget(self.badge)
        top.addStretch()
        src.addLayout(top)
        self.source_dir = PathLabel()
        src.addWidget(self.source_dir)
        g.addLayout(src, 0, 1)
        b_src = QPushButton("Выбрать…")
        b_src.clicked.connect(self.choose_source)
        g.addWidget(b_src, 0, 2)

        g.addWidget(label("Магазины", "muted"), 1, 0)
        stores_box = QVBoxLayout()
        self.stores_row = QHBoxLayout()
        self.stores_row.setSpacing(16)
        stores_box.addLayout(self.stores_row)
        self.stores_warn = label("отметьте хотя бы один магазин", "warn")
        stores_box.addWidget(self.stores_warn)
        g.addLayout(stores_box, 1, 1)
        self.all_stores_btn = QPushButton("Все")
        self.all_stores_btn.clicked.connect(self.toggle_all_stores)
        g.addWidget(self.all_stores_btn, 1, 2)

        g.addWidget(label("Основная папка", "muted"), 2, 0)
        tgt = QVBoxLayout()
        self.target_name = label()
        self.target_hint = PathLabel()
        tgt.addWidget(self.target_name)
        tgt.addWidget(self.target_hint)
        g.addLayout(tgt, 2, 1)
        self.root_btn = b_tgt = QPushButton("Изменить…")
        b_tgt.clicked.connect(self.choose_root)
        g.addWidget(b_tgt, 2, 2)

        g.addWidget(label("Ссылки", "muted"), 3, 0)
        lk = QVBoxLayout()
        self.links_name = label()
        self.links_dir = PathLabel()
        self.links_hint = label("", "caption", wrap=True)
        lk.addWidget(self.links_name)
        lk.addWidget(self.links_dir)
        lk.addWidget(self.links_hint)
        self.fill_btn = QPushButton("✨  Заполнить автоматически")
        self.fill_btn.setToolTip("Подобрать ссылки на товары для выбранной таблицы")
        self.fill_btn.clicked.connect(self.fill_links)
        self.fill_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lk.addWidget(self.fill_btn)
        g.addLayout(lk, 3, 1)
        mb = self.open_links_btn = QPushButton("Открыть")
        mb.clicked.connect(lambda: open_path(self.effective_links()))
        g.addWidget(mb, 3, 2)
        self.setup_widgets = [b_src, b_tgt, mb]
        return c

    def _idle_card(self):
        c = card()
        v = QVBoxLayout(c)
        v.addWidget(label("Выберите таблицу, папку для результатов и нажмите «Запустить».  "
                          "Таблицу можно просто перетащить в окно."))
        v.addWidget(label("Цены НОСИМО берутся из таблицы — обновите их кнопкой «Цены НОСИМО» (galaxystore.ru) "
                          "или внесите из 1С. Во время прогона откроется окно Chrome: не закрывайте его.",
                          "muted", wrap=True))
        self.last_btn = QPushButton()
        self.last_btn.setFlat(True)
        self.last_btn.setStyleSheet("color:#2f6fed; text-align:left; border:none; padding:0")
        self.last_btn.clicked.connect(lambda: open_path(self.settings.value("lastResult")))
        v.addWidget(self.last_btn, 0, Qt.AlignLeft)
        return c

    def _progress_card(self):
        c = card()
        v = QVBoxLayout(c)
        top = QHBoxLayout()
        self.percent = label("0 %", "percent")
        top.addWidget(self.percent)
        col = QVBoxLayout()
        self.count_label = label()
        self.count_label.setFont(QFont(self.count_label.font().family(), 13, QFont.Bold))
        self.timing = label("", "muted")
        col.addWidget(self.count_label)
        col.addWidget(self.timing)
        top.addLayout(col, 1)
        self.err_badge = label("", "warn")
        top.addWidget(self.err_badge)
        v.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        # Заглушка антибота: человек может пройти проверку в окне Chrome
        self.antibot_banner = label("", None, wrap=True)
        self.antibot_banner.setStyleSheet(f"background:{ORANGE}; color:white; border-radius:6px; padding:8px; font-weight:bold")
        v.addWidget(self.antibot_banner)
        self.retry_label = label("", "muted")
        v.addWidget(self.retry_label)
        self.chrome_hint = label("Окно Chrome не закрывайте — без него Ozon и Wildberries не пускают", "caption")
        v.addWidget(self.chrome_hint)
        return c

    def _result_card(self):
        c = card()
        v = QVBoxLayout(c)
        self.result_title = label()
        self.result_title.setFont(QFont(self.result_title.font().family(), 13, QFont.Bold))
        v.addWidget(self.result_title)
        self.notice_label = label("", "muted", wrap=True)
        v.addWidget(self.notice_label)
        self.tail_box = QTextEdit()
        self.tail_box.setReadOnly(True)
        self.tail_box.setMaximumHeight(120)
        self.tail_box.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 9))
        v.addWidget(self.tail_box)
        h = QHBoxLayout()
        self.open_btn = QPushButton()
        self.open_btn.setObjectName("primary")
        self.open_btn.clicked.connect(lambda: self.saved and open_path(self.saved[0]))
        self.shot_btn = QPushButton("🖼  Скриншот")
        self.shot_btn.clicked.connect(lambda: self.screenshots and open_path(self.screenshots[0]))
        self.reveal_btn = QPushButton("📁  Показать в папке")
        self.reveal_btn.clicked.connect(lambda: self.saved and reveal(self.saved[0]))
        self.log_btn = QPushButton("📄  Лог")
        self.log_btn.clicked.connect(lambda: self.log_file and open_path(self.log_file))
        self.links_btn = QPushButton("🔗  Открыть файл ссылок")
        self.links_btn.clicked.connect(lambda: open_path(self.effective_links()))
        for b in (self.open_btn, self.shot_btn, self.reveal_btn, self.log_btn, self.links_btn):
            h.addWidget(b)
        h.addStretch()
        v.addLayout(h)
        self.missing_btn = QPushButton()
        self.missing_btn.setFlat(True)
        self.missing_btn.setStyleSheet("text-align:left; border:none; padding:0")
        self.missing_btn.clicked.connect(lambda: self.missing_box.setVisible(not self.missing_box.isVisible()))
        v.addWidget(self.missing_btn, 0, Qt.AlignLeft)
        self.missing_box = QTextEdit()
        self.missing_box.setReadOnly(True)
        self.missing_box.setMaximumHeight(140)
        self.missing_box.hide()
        v.addWidget(self.missing_box)
        return c

    def _feed_card(self):
        c = card()
        v = QVBoxLayout(c)
        v.setContentsMargins(6, 6, 6, 6)
        self.feed = QTreeWidget()
        self.feed.setHeaderLabels(["", "Артикул / модель", "Магазин", "Цена", "Примечание"])
        self.feed.setRootIsDecorated(False)
        self.feed.setUniformRowHeights(True)
        hdr = self.feed.header()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        for i, w in enumerate([28, 200, 190, 110]):
            self.feed.setColumnWidth(i, w)
        hdr.setStretchLastSection(True)
        v.addWidget(self.feed)
        return c

    # --- выбор файлов и магазинов ---

    def adopt_into_root(self, path):
        """Таблица из другого места копируется в «Таблицы» основной папки, дальше работаем с копией.
        Если там уже есть другой файл с тем же именем — спрашиваем: заменить (старый — в резервные копии) или оставить."""
        if not self.root:
            return path
        folder = self.root / "Таблицы"
        if path.parent.resolve() == folder.resolve():
            return path
        dst = folder / path.name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                if filecmp.cmp(path, dst, shallow=False):
                    return dst
                if not self.confirm(f"В «Таблицы» уже есть «{path.name}»",
                                    "Заменить его выбранным файлом? Прежний сохранится в "
                                    "«Таблицы/Резервные копии таблиц».", "Заменить"):
                    return dst
                backups = folder / "Резервные копии таблиц"
                backups.mkdir(exist_ok=True)
                shutil.move(str(dst), str(backups / f"{path.stem} {datetime.now():%Y-%m-%d %H-%M-%S}{path.suffix}"))
            shutil.copy2(path, dst)
            return dst
        except OSError:  # не получилось скопировать — работаем с файлом на месте
            return path

    def set_source(self, path):
        self.source = self.adopt_into_root(Path(path))
        self.settings.setValue("sourceFile", str(self.source))
        self.table_type = None
        self.refresh()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            info = detect_table(self.source)
        finally:
            QApplication.restoreOverrideCursor()
        self.table_type = info.get("table")
        self.build_store_checks(info.get("stores", []))
        self.refresh()

    def build_store_checks(self, stores):
        """Галочки магазинов выбранной таблицы; выбор запоминается отдельно для ТВ и смартфонов."""
        while self.stores_row.count():  # убрать прежние галочки и распорку
            item = self.stores_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.store_checks = {}
        saved = self.settings.value(f"stores/{self.table_type}") if self.table_type else None
        saved = set(saved if isinstance(saved, list) else ([saved] if saved else [])) if saved is not None else None
        for s in stores:
            cb = QCheckBox(s["name"])
            cb.setChecked(saved is None or s["key"] in saved)
            cb.toggled.connect(self.save_stores)
            self.stores_row.addWidget(cb)
            self.store_checks[s["key"]] = cb
        self.stores_row.addStretch()

    def selected_stores(self):
        return [k for k, cb in self.store_checks.items() if cb.isChecked()]

    def save_stores(self, *_):
        if self.table_type:
            # пустой список QSettings сохраняет как None — храним явный маркер
            self.settings.setValue(f"stores/{self.table_type}", self.selected_stores() or [""])
        self.refresh()

    def toggle_all_stores(self):
        target = len(self.selected_stores()) != len(self.store_checks)
        for cb in self.store_checks.values():
            cb.blockSignals(True)
            cb.setChecked(target)
            cb.blockSignals(False)
        self.save_stores()

    def choose_source(self):
        tables = self.root / "Таблицы" if self.root else None
        start = str(tables if tables and tables.exists() else self.source.parent if self.source else Path.home())
        f, _ = QFileDialog.getOpenFileName(self, "Таблица мониторинга", start, "Excel (*.xlsx)")
        if f:
            self.set_source(f)

    def choose_root(self):
        """Основная папка (при первом запуске — сразу). Новую папку можно создать прямо в окне выбора."""
        d = QFileDialog.getExistingDirectory(
            self, "Основная папка мониторинга: здесь появятся «Ссылки» и папки по датам",
            str(self.root or Path.home() / "Documents"))
        if d:
            self.root = Path(d)
            self.settings.setValue("rootDirectory", d)
            if self.source:  # выбранная таблица переезжает в «Таблицы»
                return self.set_source(self.source)
        self.refresh()

    def dragEnterEvent(self, e):
        if not self.busy() and any(u.toLocalFile().lower().endswith(".xlsx") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".xlsx"):
                self.set_source(u.toLocalFile())
                break

    # --- действия ---

    def root_args(self):
        """--root и прежний файл ссылок (до основной папки он выбирался вручную) — его переносят в «Ссылки» один раз."""
        legacy = self._path_setting("linksFile", must_exist=True)
        return ["--root", str(self.root)] + (["--legacy-links", str(legacy)] if legacy else [])

    def can_start(self):
        return bool(self.source and self.table_type and self.root and not self.busy())

    def busy(self):
        return self.phase in ("syncing", "running", "stopping")

    def confirm(self, title, text, ok):
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(title)
        box.setInformativeText(text)
        yes = box.addButton(ok, QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def start_or_stop(self):
        if self.busy():
            self.stop()
        elif self.can_start() and self.selected_stores():
            self.mode = "prices"
            self.begin("syncing")
            self.launch("make_links", ["--file", str(self.source)] + self.root_args(),
                        then=self.start_prices)

    def start_prices(self, code):
        if self.phase == "stopping":
            return self.end("stopped")
        if code != 0:
            self.fail_message, self.crashed = "Не удалось обновить файл ссылок", True
            return self.end("failed")
        self.phase = "running"
        self.refresh()
        stores = self.selected_stores()
        only = [] if len(stores) == len(self.store_checks) else ["--stores", ",".join(stores)]
        self.launch("run", ["--json", "--file", str(self.source)] + self.root_args() + only,
                    then=self.finish_run)

    def fill_links(self):
        if not self.can_start():
            return
        if not self.confirm("Заполнить ссылки автоматически?",
                            f"Ссылки будут подобраны заново для таблицы «{self.source.name}»: ТВ — М.Видео и DNS, "
                            "смартфоны — М.Видео, DNS, МТС и samsungstore (по модели и памяти; на М.Видео — сначала "
                            "карточки самого М.Видео, иначе продавец маркетплейса). Берётся самая дешёвая карточка в наличии. Если товар не найден, "
                            "прежняя ссылка останется. Копия текущего файла сохранится в «Резервные копии ссылок».",
                            "Заполнить"):
            return
        self.mode = "links"
        self.begin("running")
        self.launch("fill_links", ["--json", "--file", str(self.source)] + self.root_args(),
                    then=self.finish_run)

    def update_nosimo(self):
        if not self.can_start():
            return
        if not self.confirm("Обновить цены НОСИМО с galaxystore.ru?",
                            f"Колонка НОСИМО в таблице «{self.source.name}» будет заполнена ценами с galaxystore.ru "
                            "(вместо цен из 1С). Если товара нет в наличии — всё равно ставится цена, "
                            "если его нет на сайте — «-». Копия файла сохранится в «Резервные копии таблиц».",
                            "Обновить"):
            return
        self.mode = "nosimo"
        self.begin("running")
        self.launch("nosimo", ["--json", "--file", str(self.source)], then=self.finish_run)

    def begin(self, phase):
        self.reset_state()
        self.feed.clear()
        for i in reversed(range(self.stores_grid.count())):
            self.stores_grid.itemAt(i).widget().deleteLater()
        self.phase = phase
        self.started = time.time()
        fd, name = tempfile.mkstemp(prefix="monitoring-stop-")
        os.close(fd)
        os.remove(name)
        self.stop_file = Path(name)
        self.refresh()

    def launch(self, tool, args, then):
        program, full = tool_command(tool, args + ["--stop-file", str(self.stop_file)]
                                     if tool != "make_links" else args)
        p = QProcess(self)
        p.setProgram(program)
        p.setArguments(full)
        p.setWorkingDirectory(str(APP_DIR))
        env = QProcessEnvironment.systemEnvironment()
        for k, v in child_env().items():
            env.insert(k, v)
        p.setProcessEnvironment(env)
        p.setProcessChannelMode(QProcess.MergedChannels)
        buf = {"data": b""}

        def read():
            buf["data"] += bytes(p.readAllStandardOutput())
            *lines, buf["data"] = buf["data"].split(b"\n")
            for line in lines:
                self.handle(line.decode("utf-8", "replace").rstrip("\r"))

        p.readyReadStandardOutput.connect(read)
        p.finished.connect(lambda code, _status: (read(), then(code)))
        self.process = p
        p.start()

    def stop(self):
        if self.busy() and self.stop_file:
            self.phase = "stopping"
            self.stop_file.touch()
            self.refresh()

    def finish_run(self, code):
        if self.phase == "stopping":
            self.end("stopped")
        elif self.phase == "failed":
            self.end("failed")
        elif code == 0:
            self.end("finished")
        else:
            self.fail_message = f"Прервалось с ошибкой (код {code})"
            self.crashed = True
            self.end("failed")

    def end(self, phase):
        self.phase = phase
        self.finished = time.time()
        self.process = None
        self.antibot, self.retry_note = [], ""
        if self.stop_file and self.stop_file.exists():
            self.stop_file.unlink()
        QApplication.alert(self)
        QApplication.beep()
        self.refresh()

    # --- события скрипта ---

    def handle(self, line):
        if not line.startswith("@@"):
            self.tail = (self.tail + [line])[-40:]
            return
        try:
            ev = json.loads(line[2:])
        except ValueError:
            return
        kind = ev.get("type")
        if kind == "plan":
            self.total = ev.get("total", 0)
            for s in ev.get("stores", []):  # второй план (после обновления ссылок) — строки ниже прежних
                self.stores[s["name"]] = StoreRow(self.stores_grid, len(self.stores), s["name"], s["total"])
        elif kind == "item":
            self.done, self.total = ev.get("done", self.done), ev.get("total", self.total)
            self.eta = ev.get("eta") if self.done < self.total else None
            status, retry = ev.get("status"), bool(ev.get("retry"))
            if retry:
                self.errors -= 1
            elif status == "ошибка":
                self.errors += 1
            row = self.stores.get(ev.get("store"))
            if row:
                row.add(status, retry)
            sym = {"ok": "✓", "ошибка": "⚠"}.get(status, "–")
            item = QTreeWidgetItem([sym, ev.get("article", ""), ev.get("store", ""), fmt_price(ev.get("price")),
                                    ev.get("note", "")])
            item.setForeground(0, QColor(GREEN if status == "ok" else ORANGE if status == "ошибка" else GRAY))
            item.setToolTip(4, ev.get("note", ""))
            self.feed.insertTopLevelItem(0, item)
            while self.feed.topLevelItemCount() > FEED_LIMIT:
                self.feed.takeTopLevelItem(self.feed.topLevelItemCount() - 1)
        elif kind == "antibot":
            site = ev.get("site") or "сайте"
            if ev.get("active"):
                if site not in self.antibot:
                    self.antibot.append(site)
                QApplication.alert(self)  # мигает значок на панели задач
                QApplication.beep()
            elif site in self.antibot:
                self.antibot.remove(site)
        elif kind == "retry_round":
            self.retry_note = (f"↻ {ev.get('store')}: повторяю ошибки ({ev.get('count')}), "
                               f"круг {ev.get('round')} из {ev.get('rounds')}")
        elif kind == "missing_links":
            self.missing_links = ev.get("items", [])
        elif kind == "saved":
            self.changed += ev.get("changed", 0)
            if ev.get("path"):
                self.saved.append(ev["path"])
                if self.mode == "prices":
                    self.settings.setValue("lastResult", ev["path"])
        elif kind == "screenshot":
            self.screenshots.append(ev.get("path"))
        elif kind == "summary":
            self.errors = ev.get("errors", self.errors)
            if ev.get("log"):
                self.log_file = ev["log"]
        elif kind == "unsupported":
            self.notices.append(f"Автозаполнение пока не умеет: {', '.join(ev.get('stores', []))} — "
                                "эти ссылки вставляются вручную")
        elif kind == "nothing":
            self.phase = "failed"
            self.fail_message = ("Для этой таблицы автозаполнение пока не поддерживается" if self.mode == "links"
                                 else "Нечего обрабатывать: в файле ссылок нет ссылок для этой таблицы")
        self.refresh()

    # --- отрисовка состояния ---

    def tick(self):
        if self.busy():
            self.refresh_timing()

    def refresh_timing(self):
        if not self.started:
            return
        if self.busy():
            clock = fmt_clock(time.time() - self.started)
            if self.phase == "stopping":
                text = f"Останавливаю, сохраняю собранное · идёт {clock}"
            elif self.phase == "syncing":
                text = f"Проверяю файл ссылок… · идёт {clock}"
            else:
                text = f"{fmt_eta(self.eta if self.done else None)} · идёт {clock}"
        elif self.finished:
            mins = int(self.finished - self.started) // 60
            text = "Заняло меньше минуты" if mins < 1 else f"Заняло {mins} мин"
        else:
            text = ""
        self.timing.setText(text)

    def refresh(self):
        busy = self.busy()
        # шапка
        self.start_btn.setText("■  Остановить" if busy else "▶  Запустить")
        self.start_btn.setObjectName("danger" if busy else "primary")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.start_btn.setEnabled(busy and self.phase != "stopping" or (self.can_start() and bool(self.selected_stores())))
        self.nosimo_btn.setEnabled(self.can_start())
        self.fill_btn.setEnabled(self.can_start())
        for w in self.setup_widgets:
            w.setEnabled(not busy)
        has_stores = bool(self.store_checks)
        self.all_stores_btn.setVisible(has_stores)
        self.all_stores_btn.setText("Снять все" if has_stores and len(self.selected_stores()) == len(self.store_checks)
                                    else "Все")
        self.all_stores_btn.setEnabled(not busy)
        self.stores_warn.setVisible(has_stores and not self.selected_stores())
        for cb in self.store_checks.values():
            cb.setEnabled(not busy)
        # таблица
        if self.source:
            self.source_name.setText(self.source.name)
            self.source_dir.set_path(short(self.source.parent))
            self.badge.setVisible(True)
            if self.table_type:
                self.badge.setText(self.table_type)
                self.badge.setObjectName("badge")
            else:
                self.badge.setText("определяю…" if QApplication.overrideCursor() else "формат таблицы не распознан")
                self.badge.setObjectName("warn")
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
        else:
            self.source_name.setText("Выберите Excel-файл или перетащите его в окно")
            self.source_dir.set_path("")
            self.badge.setVisible(False)
        if self.root:
            self.target_name.setText(f"📁 {self.root.name}")
            self.target_hint.set_path(f"{short(self.root.parent)} — сегодня папка «{date.today().isoformat()}»: "
                                      "ТВ, Смартфоны, Ссылки, Скриншоты, Логи")
            self.root_btn.setText("Изменить…")
        else:
            self.target_name.setText("Выберите папку, где будут храниться таблицы, ссылки и скриншоты")
            self.target_hint.set_path("")
            self.root_btn.setText("Выбрать…")
        links = self.effective_links()
        if links and self.table_type:
            self.links_name.setText(f"🔗 {links.name}")
            self.links_dir.set_path(short(links.parent))
            self.links_hint.setText("ссылки М.Видео, DNS, МТС, samsungstore; новые артикулы добавляются автоматически"
                                    if links.exists() else "файла пока нет — будет создан при запуске "
                                    "(прежний файл ссылок переносится)")
        else:
            self.links_name.setText("🔗 —")
            self.links_dir.set_path("")
            self.links_hint.setText("выберите таблицу и основную папку")
        self.open_links_btn.setEnabled(bool(links and self.table_type and links.exists()))
        # карточки состояния
        self.idle_card.setVisible(self.phase == "idle")
        last = self.settings.value("lastResult")
        self.last_btn.setVisible(bool(last and Path(last).exists()))
        if last:
            self.last_btn.setText(f"▦  Открыть последний результат: {Path(last).name}")
        self.progress_card.setVisible(self.phase != "idle" and (self.total > 0 or busy))
        frac = self.done / self.total if self.total else 0
        self.percent.setText(f"{round(frac * 100)} %")
        self.count_label.setText(f"{self.done} из {self.total} проверок" if self.total else "Подготовка…")
        self.bar.setMaximum(max(self.total, 1))
        self.bar.setValue(self.done)
        self.err_badge.setText(f"⚠ {self.errors}" if self.errors else "")
        self.chrome_hint.setVisible(busy and self.mode != "nosimo")
        self.antibot_banner.setText(f"✋ Антибот: {', '.join(self.antibot)} — откройте окно Chrome и пройдите проверку, "
                                    "если она не проходит сама")
        self.antibot_banner.setVisible(busy and bool(self.antibot))
        self.retry_label.setText(self.retry_note)
        self.retry_label.setVisible(busy and bool(self.retry_note))
        self.refresh_timing()
        self.stores_card.setVisible(bool(self.stores))
        self.result_card.setVisible(self.phase in ("finished", "stopped", "failed"))
        if self.result_card.isVisible():
            self.refresh_result()
        self.setWindowTitle(f"{APP_NAME} — {round(frac * 100)}%" if busy and self.total else APP_NAME)

    def refresh_result(self):
        if self.phase == "failed":
            title, color = self.fail_message, RED
        elif self.phase == "stopped":
            title, color = "Остановлено — собранное сохранено", ORANGE
        elif self.mode == "nosimo":
            title = f"Цены НОСИМО обновлены: {self.changed}" + (
                f". Ошибок: {self.errors} — там остались прежние цены" if self.errors else "")
            color = ORANGE if self.errors else GREEN
        elif self.mode == "links":
            title = f"Ссылки обновлены: {self.changed}" + (
                f". Ошибок: {self.errors} — там остались прежние ссылки" if self.errors else "")
            color = ORANGE if self.errors else GREEN
        else:
            title = (f"Готово. Ошибок: {self.errors} — там остались старые значения, см. лог" if self.errors
                     else "Готово, ошибок нет")
            color = ORANGE if self.errors else GREEN
        self.result_title.setText(title)
        self.result_title.setStyleSheet(f"color:{color}")
        self.result_card.setStyleSheet(f"QFrame#card {{ border: 2px solid {color}; }}")
        self.notice_label.setText("\n".join(self.notices))
        self.notice_label.setVisible(bool(self.notices))
        self.tail_box.setVisible(self.crashed and bool(self.tail))
        self.tail_box.setPlainText("\n".join(self.tail))
        self.open_btn.setText("▦  Открыть файл ссылок" if self.mode == "links" else "▦  Открыть таблицу")
        self.open_btn.setVisible(bool(self.saved))
        self.shot_btn.setVisible(bool(self.screenshots))
        self.reveal_btn.setVisible(bool(self.saved))
        self.log_btn.setVisible(bool(self.log_file))
        self.links_btn.setVisible(bool(self.missing_links) and self.mode == "prices")
        self.missing_btn.setVisible(bool(self.missing_links))
        self.missing_btn.setText(f"▸ Нет ссылки в «{self.effective_links().name}»: {len(self.missing_links)} — "
                                 "эти ячейки не обновлялись")
        self.missing_box.setPlainText("\n".join(self.missing_links))

    def closeEvent(self, e):
        if self.busy() and not self.confirm("Идёт прогон", "Остановить его и закрыть программу? "
                                            "Собранное сохранится.", "Остановить и закрыть"):
            e.ignore()
            return
        if self.busy():
            self.stop()
            if self.process:
                self.process.waitForFinished(30000)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Одинаковый светлый вид на любой теме Windows (иначе тёмная тема даёт белый текст на светлых кнопках)
    app.setStyle("Fusion")
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt 6.8+
        hints.setColorScheme(Qt.ColorScheme.Light)
    pal = QPalette()
    for role, color in [(QPalette.Window, "#ffffff"), (QPalette.WindowText, "#1d1d1f"), (QPalette.Base, "#ffffff"),
                        (QPalette.AlternateBase, "#f6f6f7"), (QPalette.Text, "#1d1d1f"), (QPalette.Button, "#fbfbfc"),
                        (QPalette.ButtonText, "#1d1d1f"), (QPalette.Highlight, "#2f6fed"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#ffffff"),
                        (QPalette.ToolTipText, "#1d1d1f"), (QPalette.PlaceholderText, "#8a8a8e")]:
        pal.setColor(role, QColor(color))
    for role in (QPalette.ButtonText, QPalette.WindowText, QPalette.Text):
        pal.setColor(QPalette.Disabled, role, QColor("#a0a0a5"))
    app.setPalette(pal)
    icon_path = APP_DIR / "assets" / ("app.ico" if sys.platform == "win32" else "icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    if not w.root:  # первый запуск — сразу спрашиваем, где создать основную папку
        QTimer.singleShot(400, w.choose_root)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
