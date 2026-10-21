import AppKit
import SwiftUI

// Сборка идёт Command Line Tools без Xcode: плагина SwiftUIMacros там нет, поэтому @State/@AppStorage
// не используются — состояние интерфейса живёт в @Observable-моделях (Observation-макросы в тулчейне есть).

@main
struct MonitoringApp: App {
    @NSApplicationDelegateAdaptor private var appDelegate: AppDelegate
    private let model = AppModel()

    var body: some Scene {
        Window("Мониторинг цен", id: "main") {
            RootView(model: model)
                .frame(minWidth: 820, minHeight: 680)
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: 880, height: 860)
        .commands {
            CommandGroup(replacing: .help) {
                Button("Справка «Мониторинг цен»") { model.openHelp() }
                    .keyboardShortcut("?", modifiers: .command)
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

struct StoreOption: Identifiable, Equatable {
    let key: String
    let name: String
    var id: String { key }
}

/// Корневая модель: папка проекта, выбранная таблица и магазины, целевая папка, файл ссылок и раннер.
@Observable
final class AppModel {
    let project = ProjectLocation()
    private(set) var runner: MonitorRunner?
    var showFolderPicker = false
    var wrongFolder = false

    /// Таблица мониторинга, которую обновляем (любой .xlsx).
    private(set) var sourceFile: URL?
    /// Тип таблицы, определённый по заголовкам: «ТВ», «Смартфоны» или nil, если формат незнаком.
    private(set) var detectedTable: String?
    private(set) var isDetecting = false
    /// Магазины выбранной таблицы и отмеченные галочками (запоминаются отдельно для ТВ и смартфонов).
    private(set) var availableStores: [StoreOption] = []
    private(set) var selectedStores: Set<String> = []
    /// Основная папка: «Ссылки» (links_tv.xlsx, links_smart.xlsx) и папки дней «2026-10-22» с подпапками
    /// ТВ, Смартфоны, Ссылки (копия), Скриншоты, Логи. Спрашивается при первом запуске.
    private(set) var rootDirectory: URL?

    /// Файл ссылок выбранной таблицы — в «Ссылки» основной папки (создаётся или переносится при первом запуске).
    var linksFile: URL? {
        guard let rootDirectory, let table = detectedTable else { return nil }
        return rootDirectory.appending(path: "Ссылки/\(table == "ТВ" ? "links_tv" : "links_smart").xlsx")
    }

    /// Файл ссылок, выбранный вручную до появления основной папки, — переносится в «Ссылки» при первом запуске.
    private var legacyLinksFile: URL? { UserDefaults.standard.url(forKey: "linksFile") }

    var canStart: Bool {
        sourceFile != nil && detectedTable != nil && rootDirectory != nil && !(runner?.isBusy ?? true)
    }
    /// «Запустить» — нужен хотя бы один отмеченный магазин.
    var canStartPrices: Bool { canStart && !selectedStores.isEmpty }
    var allStoresSelected: Bool { !availableStores.isEmpty && selectedStores.count == availableStores.count }

    init() {
        let defaults = UserDefaults.standard
        rootDirectory = defaults.url(forKey: "rootDirectory")
        if project.directory != nil { runner = MonitorRunner(project: project) }
        if let saved = defaults.url(forKey: "sourceFile"), FileManager.default.fileExists(atPath: saved.path) {
            setSource(saved)
        }
        // Служебный запуск для проверки: open "Мониторинг цен.app" --args --autostart <xlsx> <основная папка> [аргументы run.py]
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "--autostart"), i + 2 < args.count {
            let file = URL(filePath: args[i + 1]), root = URL(filePath: args[i + 2])
            let extra = Array(args[(i + 3)...])
            Task {
                try? await Task.sleep(for: .seconds(3))
                runner?.start(file: file, root: root, extraArguments: extra)
            }
        }
        // Служебная проверка автозаполнения: --autofill <xlsx> <основная папка>
        if let i = args.firstIndex(of: "--autofill"), i + 2 < args.count {
            let file = URL(filePath: args[i + 1]), root = URL(filePath: args[i + 2])
            Task {
                try? await Task.sleep(for: .seconds(3))
                runner?.fillLinks(file: file, root: root)
            }
        }
    }

    /// Руководство пользователя (docs/guide.html) — открывается в браузере.
    func openHelp() {
        guard let guide = project.helpFile else { return }
        NSWorkspace.shared.open(guide)
    }

    func choose(_ url: URL) {
        wrongFolder = !project.choose(url)
        if !wrongFolder { runner = MonitorRunner(project: project) }
    }

    func setSource(_ url: URL) {
        sourceFile = url
        detectedTable = nil
        availableStores = []
        UserDefaults.standard.set(url, forKey: "sourceFile")
        guard project.directory != nil else { return }
        isDetecting = true
        Task {
            let result = await TableDetector.detect(url, project: project)
            detectedTable = result?.table
            availableStores = result?.stores ?? []
            let saved = detectedTable.flatMap { UserDefaults.standard.stringArray(forKey: "stores.\($0)") }
            selectedStores = Set(saved ?? availableStores.map(\.key)).intersection(availableStores.map(\.key))
            isDetecting = false
        }
    }

    func toggleStore(_ key: String) {
        if selectedStores.contains(key) { selectedStores.remove(key) } else { selectedStores.insert(key) }
        saveStores()
    }

    func toggleAllStores() {
        selectedStores = allStoresSelected ? [] : Set(availableStores.map(\.key))
        saveStores()
    }

    private func saveStores() {
        guard let table = detectedTable else { return }
        // порядок как в таблице — так удобнее читать в настройках
        UserDefaults.standard.set(availableStores.map(\.key).filter(selectedStores.contains), forKey: "stores.\(table)")
    }

    /// Выбор основной папки (при первом запуске — сразу). Можно создать новую прямо в окне выбора.
    func chooseRoot() {
        let panel = NSOpenPanel()
        panel.title = "Основная папка мониторинга"
        panel.message = "Где хранить мониторинг: здесь появятся папка «Ссылки» и папки по датам "
            + "(ТВ, Смартфоны, Ссылки, Скриншоты, Логи). Можно создать новую папку."
        panel.prompt = "Выбрать"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.directoryURL = rootDirectory ?? URL.documentsDirectory
        guard panel.runModal() == .OK, let url = panel.url else { return }
        rootDirectory = url
        UserDefaults.standard.set(url, forKey: "rootDirectory")
    }

    func fillLinks() {
        guard canStart, let sourceFile, let rootDirectory else { return }
        let alert = NSAlert()
        alert.messageText = "Заполнить ссылки автоматически?"
        alert.informativeText = """
            Ссылки будут подобраны заново для таблицы «\(sourceFile.lastPathComponent)»:
            ТВ — М.Видео и DNS, смартфоны — М.Видео, DNS, МТС и samsungstore (по модели и памяти; \
            на М.Видео — сначала карточки самого М.Видео, иначе продавец маркетплейса). Берётся самая дешёвая карточка в наличии.
            Если товар не найден, прежняя ссылка останется. Копия текущего файла сохранится в «Резервные копии ссылок».
            """
        alert.addButton(withTitle: "Заполнить")
        alert.addButton(withTitle: "Отмена")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        runner?.fillLinks(file: sourceFile, root: rootDirectory, links: linksFile, legacyLinks: legacyLinksFile)
    }

    func updateNosimo() {
        guard canStart, let sourceFile else { return }
        let alert = NSAlert()
        alert.messageText = "Обновить цены НОСИМО с galaxystore.ru?"
        alert.informativeText = """
            Колонка НОСИМО в таблице «\(sourceFile.lastPathComponent)» будет заполнена ценами с galaxystore.ru \
            (вместо цен из 1С). Если товара нет в наличии — всё равно ставится цена, если его нет на сайте — «-».
            Копия файла сохранится в «Резервные копии таблиц» рядом с ним.
            """
        alert.addButton(withTitle: "Обновить")
        alert.addButton(withTitle: "Отмена")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        runner?.updateNosimo(file: sourceFile)
    }

    func start() {
        guard canStartPrices, let sourceFile, let rootDirectory else { return }
        // все магазины — без фильтра; иначе только отмеченные
        let stores = allStoresSelected ? [] : ["--stores", availableStores.map(\.key).filter(selectedStores.contains)
            .joined(separator: ",")]
        runner?.start(file: sourceFile, root: rootDirectory, links: linksFile, legacyLinks: legacyLinksFile,
                      extraArguments: stores)
    }

    /// Папка дня в основной папке.
    var todayFolderName: String { Date.now.formatted(.iso8601.year().month().day()) }
}

/// Определяет тип таблицы и её магазины через `run.py --detect` — единая логика с Python-частью.
enum TableDetector {
    static func detect(_ file: URL, project: ProjectLocation) async -> (table: String, stores: [StoreOption])? {
        guard let dir = project.directory, let command = project.command(["run.py", "--detect", file.path]) else {
            return nil
        }
        return await withCheckedContinuation { (continuation: CheckedContinuation<(table: String, stores: [StoreOption])?, Never>) in
            let process = Process()
            process.executableURL = command.executable
            process.arguments = command.arguments
            process.currentDirectoryURL = dir
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = FileHandle.nullDevice
            process.terminationHandler = { _ in
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                guard let table = json?["table"] as? String else { return continuation.resume(returning: nil) }
                let stores = (json?["stores"] as? [[String: String]] ?? []).compactMap { item -> StoreOption? in
                    guard let key = item["key"], let name = item["name"] else { return nil }
                    return StoreOption(key: key, name: name)
                }
                continuation.resume(returning: (table, stores))
            }
            do {
                try process.run()
            } catch {
                continuation.resume(returning: nil)
            }
        }
    }
}

struct RootView: View {
    let model: AppModel

    var body: some View {
        if let runner = model.runner {
            ContentView(model: model, runner: runner)
        } else {
            ProjectPickerView(model: model)
        }
    }
}

struct ProjectPickerView: View {
    let model: AppModel

    var body: some View {
        ContentUnavailableView {
            Label("Не найдена папка мониторинга", systemImage: "folder.badge.questionmark")
        } description: {
            Text("Укажите папку, где лежат run.py и .venv.")
            if model.wrongFolder {
                Text("В выбранной папке нет run.py или .venv").foregroundStyle(.red)
            }
        } actions: {
            Button("Выбрать папку…") { model.showFolderPicker = true }
                .buttonStyle(.borderedProminent)
        }
        .fileImporter(
            isPresented: Binding(get: { model.showFolderPicker }, set: { model.showFolderPicker = $0 }),
            allowedContentTypes: [.folder]
        ) { result in
            if case .success(let url) = result { model.choose(url) }
        }
    }
}
