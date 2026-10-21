import AppKit
import Foundation
import Observation

struct StoreProgress: Identifiable, Equatable {
    let name: String
    let total: Int
    var ok = 0
    var missing = 0
    var errors = 0

    var id: String { name }
    var done: Int { ok + missing + errors }
}

struct FeedItem: Identifiable, Equatable {
    let id: Int
    let store: String
    let article: String
    let status: Status
    let price: Int?
    let note: String

    enum Status: Equatable {
        case ok, missing, error
    }
}

/// Запускает Python-часть мониторинга и превращает её события (`@@{json}`) в состояние для интерфейса.
@Observable
final class MonitorRunner {
    enum Phase: Equatable {
        case idle
        case syncingLinks
        case running
        case stopping
        case finished(stopped: Bool)
        case failed(String)
    }

    /// Что запускали: сбор цен, автозаполнение файла ссылок или цены НОСИМО.
    enum Mode: Equatable { case prices, links, nosimo }

    private(set) var phase: Phase = .idle
    private(set) var mode: Mode = .prices
    /// Сколько ячеек изменено (для ссылок — сколько ссылок обновлено).
    private(set) var changedCount = 0
    /// Пояснения от скрипта (например, какие магазины автозаполнение не поддерживает).
    private(set) var notices: [String] = []
    private(set) var total = 0
    private(set) var done = 0
    private(set) var etaSeconds: Int?
    private(set) var startedAt: Date?
    private(set) var finishedAt: Date?
    private(set) var stores: [StoreProgress] = []
    private(set) var feed: [FeedItem] = []
    private(set) var savedFiles: [URL] = []
    private(set) var screenshots: [URL] = []
    private(set) var logFile: URL?
    private(set) var linksFile: URL?
    /// Скрипт упал (а не сообщил понятную причину) — показываем его последние строки.
    private(set) var crashed = false
    private(set) var errorCount = 0
    private(set) var missingLinks: [String] = []
    private(set) var syncMessages: [String] = []
    /// Последние строки обычного вывода — показываются, если прогон упал.
    private(set) var tailOutput: [String] = []

    let project: ProjectLocation

    @ObservationIgnored private var process: Process?
    @ObservationIgnored private var feedCounter = 0
    private static let feedLimit = 300

    init(project: ProjectLocation) {
        self.project = project
    }

    var isBusy: Bool {
        switch phase {
        case .syncingLinks, .running, .stopping: true
        default: false
        }
    }

    var fraction: Double { total > 0 ? Double(done) / Double(total) : 0 }

    /// file — таблица мониторинга, root — основная папка (ссылки в «Ссылки», результаты в папке дня).
    func start(file: URL, root: URL, links: URL? = nil, legacyLinks: URL? = nil, extraArguments: [String] = []) {
        let rootArguments = Self.rootArguments(root, legacyLinks)
        guard !isBusy, let dir = project.directory else { return }
        reset()
        mode = .prices
        linksFile = links
        phase = .syncingLinks
        startedAt = .now
        Task {
            let syncStatus = await execute(["make_links_template.py", "--file", file.path] + rootArguments, in: dir) { line in
                self.syncMessages.append(line)
            }
            if phase == .stopping {  // остановили во время синхронизации файла ссылок
                phase = .finished(stopped: true)
                return finish()
            }
            guard syncStatus == 0 else {
                phase = .failed("Не удалось обновить файл ссылок")
                crashed = true
                return finish()
            }
            phase = .running
            let arguments = ["run.py", "--json", "--file", file.path] + rootArguments + extraArguments
            let status = await execute(arguments, in: dir) { line in
                self.handle(line)
            }
            if phase == .stopping {
                phase = .finished(stopped: true)
            } else if case .failed = phase {
                // уже объяснили причину (например, «Нечего обрабатывать»)
            } else if status == 0 {
                phase = .finished(stopped: false)
            } else {
                phase = .failed("Прогон прервался с ошибкой (код \(status))")
                crashed = true
            }
            finish()
        }
    }

    /// Подбор ссылок по таблице (fill_links.py). Перед записью скрипт делает резервную копию.
    func fillLinks(file: URL, root: URL, links: URL? = nil, legacyLinks: URL? = nil) {
        linksFile = links
        runTool(.links, ["fill_links.py", "--json", "--file", file.path] + Self.rootArguments(root, legacyLinks))
    }

    /// --root и прежний файл ссылок (до основной папки он выбирался вручную) — его переносят в «Ссылки» один раз.
    private static func rootArguments(_ root: URL, _ legacyLinks: URL?) -> [String] {
        ["--root", root.path] + (legacyLinks.map { ["--legacy-links", $0.path] } ?? [])
    }

    /// Цены НОСИМО с galaxystore.ru в колонку НОСИМО выбранной таблицы (nosimo.py, с резервной копией).
    func updateNosimo(file: URL) {
        runTool(.nosimo, ["nosimo.py", "--json", "--file", file.path])
    }

    private func runTool(_ mode: Mode, _ arguments: [String]) {
        guard !isBusy, let dir = project.directory else { return }
        let links = linksFile
        reset()
        linksFile = links
        self.mode = mode
        phase = .running
        startedAt = .now
        Task {
            let status = await execute(arguments, in: dir) { line in
                self.handle(line)
            }
            if phase == .stopping {
                phase = .finished(stopped: true)
            } else if case .failed = phase {
            } else if status == 0 {
                phase = .finished(stopped: false)
            } else {
                phase = .failed("Прервалось с ошибкой (код \(status))")
                crashed = true
            }
            finish()
        }
    }

    /// SIGINT: скрипт отменяет задачи и сохраняет то, что успел собрать.
    func stop() {
        guard isBusy, let process else { return }
        phase = .stopping
        process.interrupt()
    }

    func revealResults() {
        if !savedFiles.isEmpty {
            NSWorkspace.shared.activateFileViewerSelecting(savedFiles)
        }
    }

    // MARK: - Внутреннее

    private func reset() {
        total = 0; done = 0; etaSeconds = nil; finishedAt = nil
        stores = []; feed = []; savedFiles = []; screenshots = []; logFile = nil
        errorCount = 0; missingLinks = []; syncMessages = []; tailOutput = []; crashed = false
        changedCount = 0; notices = []
        feedCounter = 0
        updateDockBadge()
    }

    private func finish() {
        process = nil
        finishedAt = .now
        etaSeconds = nil
        NSApp.dockTile.badgeLabel = nil
        NSApp.requestUserAttention(.informationalRequest)
        NSSound(named: "Glass")?.play()
    }

    private func handle(_ line: String) {
        guard line.hasPrefix("@@") else {
            tailOutput.append(line)
            if tailOutput.count > 40 { tailOutput.removeFirst(tailOutput.count - 40) }
            return
        }
        guard let data = line.dropFirst(2).data(using: .utf8),
              let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = event["type"] as? String
        else { return }

        switch type {
        case "plan":
            total = event["total"] as? Int ?? 0
            let list = event["stores"] as? [[String: Any]] ?? []
            // второй план (после обновления ссылок М.Видео) — добавляем строки ниже прежних
            stores += list.compactMap { item in
                guard let name = item["name"] as? String, let count = item["total"] as? Int else { return nil }
                return StoreProgress(name: name, total: count)
            }
        case "item":
            apply(item: event)
        case "missing_links":
            missingLinks = event["items"] as? [String] ?? []
        case "saved":
            changedCount += event["changed"] as? Int ?? 0
            if let path = event["path"] as? String {
                savedFiles.append(URL(filePath: path))
                if mode == .prices { UserDefaults.standard.set(URL(filePath: path), forKey: "lastResult") }
            }
        case "unsupported":
            let names = (event["stores"] as? [String] ?? []).joined(separator: ", ")
            notices.append("Автозаполнение пока не умеет: \(names) — эти ссылки вставляются вручную")
        case "nothing":
            phase = .failed(mode == .links
                ? "Для этой таблицы автозаполнение пока не поддерживается"
                : "Нечего обрабатывать: в файле ссылок нет ссылок для этой таблицы")
        case "screenshot":
            if let path = event["path"] as? String { screenshots.append(URL(filePath: path)) }
        case "summary":
            errorCount = event["errors"] as? Int ?? 0
            if let path = event["log"] as? String, !path.isEmpty { logFile = URL(filePath: path) }
        default:
            break
        }
    }

    private func apply(item event: [String: Any]) {
        let storeName = event["store"] as? String ?? ""
        let status: FeedItem.Status = switch event["status"] as? String {
        case "ok": .ok
        case "ошибка": .error
        default: .missing
        }
        if let index = stores.firstIndex(where: { $0.name == storeName }) {
            switch status {
            case .ok: stores[index].ok += 1
            case .missing: stores[index].missing += 1
            case .error: stores[index].errors += 1
            }
        }
        done = event["done"] as? Int ?? done
        total = event["total"] as? Int ?? total
        etaSeconds = done < total ? event["eta"] as? Int : nil
        if status == .error { errorCount += 1 }

        feedCounter += 1
        let item = FeedItem(
            id: feedCounter,
            store: storeName,
            article: event["article"] as? String ?? "",
            status: status,
            price: event["price"] as? Int,
            note: event["note"] as? String ?? ""
        )
        feed.insert(item, at: 0)
        if feed.count > Self.feedLimit { feed.removeLast(feed.count - Self.feedLimit) }
        updateDockBadge()
    }

    private func updateDockBadge() {
        NSApp.dockTile.badgeLabel = total > 0 && done < total ? "\(Int(fraction * 100))%" : nil
    }

    /// Запускает скрипт и построчно отдаёт stdout+stderr. Возвращает код выхода.
    private func execute(_ arguments: [String], in dir: URL, onLine: @escaping (String) -> Void) async -> Int32 {
        guard let command = project.command(arguments) else {
            onLine("Не найдены скрипты мониторинга")
            return -1
        }
        let process = Process()
        process.executableURL = command.executable
        process.arguments = command.arguments
        process.currentDirectoryURL = dir
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            try process.run()
        } catch {
            onLine("Не удалось запустить скрипт: \(error.localizedDescription)")
            return -1
        }
        self.process = process
        do {
            for try await line in pipe.fileHandleForReading.bytes.lines {
                onLine(line)
            }
        } catch {
            onLine("Ошибка чтения вывода: \(error.localizedDescription)")
        }
        process.waitUntilExit()
        return process.terminationStatus
    }
}
