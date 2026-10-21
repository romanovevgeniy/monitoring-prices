import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    let model: AppModel
    let runner: MonitorRunner

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HeaderView(model: model, runner: runner)
            SetupCard(model: model, disabled: runner.isBusy)
            StatusSection(runner: runner)
            if !runner.stores.isEmpty {
                StoresCard(stores: runner.stores)
            }
            FeedCard(feed: runner.feed)
        }
        .padding(20)
        .animation(.smooth, value: runner.phase)
        // Первый запуск: сразу спрашиваем, где создать основную папку
        .task {
            guard model.rootDirectory == nil else { return }
            try? await Task.sleep(for: .milliseconds(600))
            model.chooseRoot()
        }
        // Таблицу можно просто перетащить в окно
        .dropDestination(for: URL.self) { urls, _ in
            guard !runner.isBusy, let xlsx = urls.first(where: { $0.pathExtension.lowercased() == "xlsx" }) else {
                return false
            }
            model.setSource(xlsx)
            return true
        }
    }
}

// MARK: - Шапка и настройки

private struct HeaderView: View {
    let model: AppModel
    let runner: MonitorRunner

    var body: some View {
        HStack(spacing: 14) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 52, height: 52)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text("Мониторинг цен").font(.largeTitle).bold()
                Text("М.Видео · DNS · МТС · samsungstore · Ozon · WB · Москва")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Button {
                model.openHelp()
            } label: {
                Image(systemName: "questionmark.circle")
            }
            .buttonStyle(.borderless)
            .font(.title2)
            .help("Справка — руководство пользователя (⌘?)")
            .accessibilityLabel("Справка")
            if runner.isBusy {
                Button(role: .destructive) {
                    runner.stop()
                } label: {
                    Label(runner.phase == .stopping ? "Останавливаю…" : "Остановить", systemImage: "stop.fill")
                        .frame(minWidth: 130)
                }
                .controlSize(.large)
                .disabled(runner.phase == .stopping)
                .help("Остановить — уже собранное сохранится")
            } else {
                Button {
                    model.updateNosimo()
                } label: {
                    Label("Цены НОСИМО", systemImage: "tag")
                }
                .controlSize(.large)
                .disabled(!model.canStart)
                .help("Заполнить колонку НОСИМО ценами с galaxystore.ru")
                Button {
                    model.start()
                } label: {
                    Label("Запустить", systemImage: "play.fill")
                        .frame(minWidth: 130)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
                .disabled(!model.canStartPrices)
            }
        }
    }
}

/// Что обновляем, по каким магазинам, куда сохраняем и где ссылки.
private struct SetupCard: View {
    let model: AppModel
    let disabled: Bool

    var body: some View {
        Card {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 12) {
                GridRow {
                    Text("Таблица").foregroundStyle(.secondary)
                    sourceLabel
                    Button("Выбрать…", action: chooseSource)
                }
                if !model.availableStores.isEmpty {
                    Divider().gridCellUnsizedAxes(.horizontal)
                    GridRow {
                        Text("Магазины").foregroundStyle(.secondary)
                        StoresPicker(model: model)
                        Button(model.allStoresSelected ? "Снять все" : "Все") { model.toggleAllStores() }
                    }
                }
                Divider().gridCellUnsizedAxes(.horizontal)
                GridRow {
                    Text("Основная папка").foregroundStyle(.secondary)
                    rootLabel
                    Button(model.rootDirectory == nil ? "Выбрать…" : "Изменить…") { model.chooseRoot() }
                }
                Divider().gridCellUnsizedAxes(.horizontal)
                GridRow {
                    Text("Ссылки").foregroundStyle(.secondary)
                    linksLabel
                    Button("Открыть") {
                        if let links = model.linksFile { NSWorkspace.shared.open(links) }
                    }
                    .disabled(!(model.linksFile.map { FileManager.default.fileExists(atPath: $0.path) } ?? false))
                }
            }
            .disabled(disabled)
        }
    }

    @ViewBuilder
    private var sourceLabel: some View {
        if let file = model.sourceFile {
            HStack(spacing: 8) {
                PathLabel(url: file, symbol: "tablecells.fill", color: .green)
                if model.isDetecting {
                    ProgressView().controlSize(.small)
                } else if let table = model.detectedTable {
                    Text(table)
                        .font(.caption.bold())
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(.green.opacity(0.15), in: .capsule)
                        .help("Тип таблицы определён по заголовкам")
                } else {
                    Label("Формат таблицы не распознан", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        } else {
            Text("Выберите Excel-файл или перетащите его в окно")
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private var rootLabel: some View {
        if let root = model.rootDirectory {
            VStack(alignment: .leading, spacing: 2) {
                PathLabel(url: root, symbol: "folder.fill", color: .blue)
                Text("сегодня — папка «\(model.todayFolderName)»: ТВ, Смартфоны, Ссылки, Скриншоты, Логи")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } else {
            Text("Выберите папку, где будут храниться таблицы, ссылки и скриншоты")
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private var linksLabel: some View {
        if let links = model.linksFile {
            VStack(alignment: .leading, spacing: 2) {
                PathLabel(url: links, symbol: "link", color: .purple)
                Text(FileManager.default.fileExists(atPath: links.path)
                     ? "ссылки М.Видео, DNS, МТС, samsungstore; новые артикулы добавляются автоматически"
                     : "файла пока нет — будет создан при запуске (прежний файл ссылок переносится)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button {
                    model.fillLinks()
                } label: {
                    Label("Заполнить автоматически", systemImage: "wand.and.stars")
                }
                .controlSize(.small)
                .disabled(!model.canStart)
                .help("Подобрать ссылки на товары для выбранной таблицы")
                .padding(.top, 4)
            }
        }
    }

    private func chooseSource() {
        let panel = NSOpenPanel()
        panel.title = "Таблица мониторинга"
        panel.allowedContentTypes = [UTType(filenameExtension: "xlsx") ?? .spreadsheet]
        panel.directoryURL = model.tablesDirectory.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil }
            ?? model.sourceFile?.deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url { model.setSource(url) }
    }
}

/// Галочки магазинов, по которым собирать цены.
private struct StoresPicker: View {
    let model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 16) {
                ForEach(model.availableStores) { store in
                    Toggle(store.name, isOn: Binding(
                        get: { model.selectedStores.contains(store.key) },
                        set: { _ in model.toggleStore(store.key) }
                    ))
                    .toggleStyle(.checkbox)
                }
            }
            if model.selectedStores.isEmpty {
                Text("отметьте хотя бы один магазин").font(.caption).foregroundStyle(.orange)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Имя файла/папки крупно, путь до него — мелко и с сокращением середины.
private struct PathLabel: View {
    let url: URL
    let symbol: String
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).foregroundStyle(color)
            VStack(alignment: .leading, spacing: 0) {
                Text(url.lastPathComponent).lineLimit(1)
                Text(url.deletingLastPathComponent().path.replacing(URL.homeDirectory.path, with: "~"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .help(url.path)
    }
}

// MARK: - Статус и прогресс

private struct StatusSection: View {
    let runner: MonitorRunner

    var body: some View {
        switch runner.phase {
        case .idle:
            IdleCard(project: runner.project)
        case .syncingLinks:
            Card {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("Проверяю файл ссылок — новые и удалённые артикулы…")
                }
            }
        case .running, .stopping:
            ProgressCard(runner: runner)
        case .finished, .failed:
            VStack(spacing: 12) {
                if runner.total > 0 { ProgressCard(runner: runner) }
                ResultBanner(runner: runner)
            }
        }
    }
}

private struct IdleCard: View {
    let project: ProjectLocation

    var body: some View {
        Card {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "info.circle").foregroundStyle(.secondary).font(.title3)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Выберите таблицу, папку для результатов и нажмите «Запустить».")
                    Text("Цены НОСИМО берутся из таблицы — обновите их кнопкой «Цены НОСИМО» (galaxystore.ru) или внесите из 1С. Во время прогона откроется окно Chrome: не закрывайте его.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if let latest = project.latestResult {
                        Button {
                            NSWorkspace.shared.open(latest)
                        } label: {
                            Label("Открыть последний результат: \(latest.lastPathComponent)", systemImage: "tablecells")
                        }
                        .buttonStyle(.link)
                        .padding(.top, 2)
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }
}

private struct ProgressCard: View {
    let runner: MonitorRunner

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline, spacing: 14) {
                    Text(runner.fraction, format: .percent.precision(.fractionLength(0)))
                        .font(.system(size: 44, weight: .bold, design: .rounded))
                        .monospacedDigit()
                        .contentTransition(.numericText())
                    VStack(alignment: .leading, spacing: 3) {
                        Text("\(runner.done) из \(runner.total) проверок")
                            .font(.headline)
                            .monospacedDigit()
                        TimingText(runner: runner)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if runner.errorCount > 0 {
                        Label("\(runner.errorCount)", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                            .help("Ошибок: в этих ячейках останутся старые значения")
                    }
                }
                ProgressView(value: runner.fraction)
                    .progressViewStyle(.linear)
                    .tint(runner.phase == .stopping ? .orange : .accentColor)
                if runner.isBusy && runner.mode != .nosimo {
                    Label("Окно Chrome не закрывайте — без него Ozon и Wildberries не пускают", systemImage: "safari")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .animation(.smooth, value: runner.done)
        }
    }
}

/// «Осталось ~12 мин · идёт 05:01» — секундомер обновляется раз в секунду только во время прогона.
private struct TimingText: View {
    let runner: MonitorRunner

    var body: some View {
        if runner.isBusy, let start = runner.startedAt {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(line(elapsed: context.date.timeIntervalSince(start)))
            }
        } else if let start = runner.startedAt, let end = runner.finishedAt {
            Text("Заняло \(Format.duration(end.timeIntervalSince(start)))")
        }
    }

    private func line(elapsed: TimeInterval) -> String {
        let clock = Format.clock(elapsed)
        if runner.phase == .stopping { return "Останавливаю, сохраняю собранное · идёт \(clock)" }
        guard let eta = runner.etaSeconds, runner.done > 0 else { return "Оцениваю время… · идёт \(clock)" }
        return "Осталось \(Format.eta(eta)) · идёт \(clock)"
    }
}

private struct ResultBanner: View {
    let runner: MonitorRunner

    var body: some View {
        Card(tint: tint) {
            VStack(alignment: .leading, spacing: 10) {
                Label(title, systemImage: icon)
                    .font(.headline)
                    .foregroundStyle(tint)
                if runner.crashed, !runner.tailOutput.isEmpty {
                    ScrollView {
                        Text(runner.tailOutput.joined(separator: "\n"))
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 120)
                }
                HStack(spacing: 10) {
                    if let file = runner.savedFiles.first {
                        Button {
                            NSWorkspace.shared.open(file)
                        } label: {
                            Label(runner.mode == .links ? "Открыть файл ссылок" : "Открыть таблицу", systemImage: "tablecells")
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    if let shot = runner.screenshots.first {
                        Button {
                            NSWorkspace.shared.open(shot)
                        } label: {
                            Label("Скриншот", systemImage: "photo")
                        }
                    }
                    if !runner.savedFiles.isEmpty {
                        Button {
                            runner.revealResults()
                        } label: {
                            Label("Показать в Finder", systemImage: "folder")
                        }
                    }
                    if !runner.missingLinks.isEmpty, runner.mode == .prices, let links = runner.linksFile {
                        Button {
                            NSWorkspace.shared.open(links)
                        } label: {
                            Label("Открыть файл ссылок", systemImage: "link")
                        }
                    }
                    if let log = runner.logFile {
                        Button {
                            NSWorkspace.shared.open(log)
                        } label: {
                            Label("Лог", systemImage: "doc.text")
                        }
                    }
                }
                ForEach(runner.notices, id: \.self) { notice in
                    Label(notice, systemImage: "info.circle")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                if !runner.missingLinks.isEmpty {
                    DisclosureGroup("Нет ссылки в «\(runner.linksFile?.lastPathComponent ?? "файле ссылок")»: \(runner.missingLinks.count) — эти ячейки не обновлялись") {
                        Text(runner.missingLinks.joined(separator: "\n"))
                            .font(.callout)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .font(.callout)
                }
            }
        }
    }

    private var title: String {
        switch runner.phase {
        case .finished(stopped: true): "Остановлено — собранное сохранено"
        case .failed(let message): message
        default:
            if runner.mode == .nosimo {
                "Цены НОСИМО обновлены: \(runner.changedCount)" + (runner.errorCount > 0
                    ? ". Ошибок: \(runner.errorCount) — там остались прежние цены" : "")
            } else if runner.mode == .links {
                "Ссылки обновлены: \(runner.changedCount)" + (runner.errorCount > 0
                    ? ". Ошибок: \(runner.errorCount) — там остались прежние ссылки" : "")
            } else if runner.errorCount > 0 {
                "Готово. Ошибок: \(runner.errorCount) — там остались старые значения, см. лог"
            } else {
                "Готово, ошибок нет"
            }
        }
    }

    private var icon: String {
        switch runner.phase {
        case .failed: "xmark.octagon.fill"
        case .finished(stopped: true): "pause.circle.fill"
        default: runner.errorCount > 0 ? "exclamationmark.triangle.fill" : "checkmark.circle.fill"
        }
    }

    private var tint: Color {
        switch runner.phase {
        case .failed: .red
        case .finished(stopped: true): .orange
        default: runner.errorCount > 0 ? .orange : .green
        }
    }
}

// MARK: - Магазины

private struct StoresCard: View {
    let stores: [StoreProgress]

    var body: some View {
        Card {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 10) {
                ForEach(stores) { store in
                    StoreRow(store: store)
                }
            }
        }
    }
}

private struct StoreRow: View {
    let store: StoreProgress

    var body: some View {
        GridRow {
            Text(store.name)
                .lineLimit(1)
                .frame(width: 190, alignment: .leading)
            ProgressView(value: Double(store.done), total: Double(max(store.total, 1)))
                .tint(store.done == store.total ? .green : .accentColor)
            Text("\(store.done)/\(store.total)")
                .monospacedDigit()
                .foregroundStyle(.secondary)
                .frame(width: 60, alignment: .trailing)
            CountBadge(count: store.ok, symbol: "checkmark.circle.fill", color: .green, help: "Найдено")
            CountBadge(count: store.missing, symbol: "minus.circle.fill", color: .secondary, help: "Нет в наличии")
            CountBadge(count: store.errors, symbol: "exclamationmark.triangle.fill", color: .orange, help: "Ошибка")
        }
        .accessibilityElement(children: .combine)
    }
}

private struct CountBadge: View {
    let count: Int
    let symbol: String
    let color: Color
    let help: String

    var body: some View {
        Label {
            Text(count, format: .number).monospacedDigit()
        } icon: {
            Image(systemName: symbol).foregroundStyle(color)
        }
        .frame(width: 58, alignment: .leading)
        .foregroundStyle(count == 0 ? .tertiary : .primary)
        .help(help)
    }
}

// MARK: - Лента результатов

private struct FeedCard: View {
    let feed: [FeedItem]

    var body: some View {
        Card(padding: 0) {
            if feed.isEmpty {
                ContentUnavailableView("Здесь появятся цены", systemImage: "list.bullet.rectangle",
                                       description: Text("по мере обхода магазинов"))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(feed) { item in
                    FeedRow(item: item)
                }
                .listStyle(.inset)
                .scrollContentBackground(.hidden)
            }
        }
        .frame(maxHeight: .infinity)
    }
}

private struct FeedRow: View {
    let item: FeedItem

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .foregroundStyle(color)
                .frame(width: 18)
            Text(item.article)
                .font(.body.monospaced())
                .lineLimit(1)
                .frame(width: 200, alignment: .leading)
            Text(item.store)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(width: 160, alignment: .leading)
            Text(Format.price(item.price))
                .monospacedDigit()
                .bold(item.price != nil)
                .frame(width: 100, alignment: .trailing)
            Text(item.note)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.tail)
                .help(item.note)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }

    private var symbol: String {
        switch item.status {
        case .ok: "checkmark.circle.fill"
        case .missing: "minus.circle.fill"
        case .error: "exclamationmark.triangle.fill"
        }
    }

    private var color: Color {
        switch item.status {
        case .ok: .green
        case .missing: .secondary
        case .error: .orange
        }
    }
}

// MARK: - Общее

private struct Card<Content: View>: View {
    var tint: Color? = nil
    var padding: Double = 14
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.secondary, in: .rect(cornerRadius: 14))
            .overlay {
                RoundedRectangle(cornerRadius: 14)
                    .strokeBorder(tint ?? Color.primary.opacity(0.08), lineWidth: tint == nil ? 1 : 1.5)
            }
    }
}

enum Format {
    private static let ru = Locale(identifier: "ru_RU")

    static func price(_ value: Int?) -> String {
        guard let value else { return "—" }
        return value.formatted(.number.locale(ru)) + " ₽"
    }

    static func eta(_ seconds: Int) -> String {
        if seconds < 60 { return "меньше минуты" }
        let minutes = (seconds + 30) / 60
        return minutes < 60 ? "~\(minutes) мин" : "~\(minutes / 60) ч \(minutes % 60) мин"
    }

    static func clock(_ interval: TimeInterval) -> String {
        let s = Int(interval)
        return s >= 3600
            ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%02d:%02d", s / 60, s % 60)
    }

    static func duration(_ interval: TimeInterval) -> String {
        let minutes = Int(interval) / 60
        if minutes < 1 { return "меньше минуты" }
        return minutes < 60 ? "\(minutes) мин" : "\(minutes / 60) ч \(minutes % 60) мин"
    }
}
