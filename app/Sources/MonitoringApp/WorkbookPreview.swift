import Foundation
import Observation

struct PreviewColumn: Decodable, Identifiable {
    let key: String
    let name: String
    var id: String { key }
}

struct PriceVerification: Decodable {
    let code: String
    let label: String
    let checkedAt: String
    let message: String
}

struct ComparisonSummary: Decodable {
    let total: Int
    let updated: Int
    let cheaper: Int
    let errors: Int
    let unconfirmed: Int
    let maxDifference: Double
}

struct RetryPair: Decodable { let article: String; let store: String }

struct PreviewRow: Decodable, Identifiable {
    let row: Int
    let article: String
    let base: String
    let baseDisplay: String
    let prices: [String]
    let lower: [Bool]
    let statuses: [PriceVerification]
    let cheaper: Bool
    let difference: Double
    var id: Int { row }
}

struct PreviewSnapshot: Decodable {
    let filename: String
    let table: String
    let template: String
    let fingerprint: String
    let columns: [PreviewColumn]
    let rows: [PreviewRow]
    let count: Int
    let summary: ComparisonSummary
    let retryPairs: [RetryPair]
}

private struct PreviewFailure: Decodable { let error: String }
private struct PriceEdit: Encodable { let row: Int; let value: String }
private struct PriceChanges: Encodable { let fingerprint: String; let edits: [PriceEdit] }

@Observable
final class WorkbookPreview {
    var filter = "all"
    var visibleRows: [PreviewRow] {
        (snapshot?.rows ?? []).filter { row in
            switch filter {
            case "cheaper": row.cheaper
            case "errors": row.statuses.contains { $0.code == "error" }
            case "unconfirmed": row.statuses.contains { !["fresh", "unavailable"].contains($0.code) }
            default: true
            }
        }
    }
    private(set) var snapshot: PreviewSnapshot?
    private(set) var file: URL?
    private(set) var isLoading = false
    private(set) var isSaving = false
    private(set) var message = "Выберите таблицу на первом шаге."
    private(set) var failed = false
    private(set) var edits: [Int: String] = [:]
    @ObservationIgnored private var generation = UUID()
    private var template = "all"
    private var stores: [String] = []
    var isDirty: Bool { !edits.isEmpty }

    func value(_ row: PreviewRow) -> String { edits[row.row] ?? row.base }

    func edit(_ row: PreviewRow, value: String) {
        if value == row.base { edits.removeValue(forKey: row.row) }
        else { edits[row.row] = value }
        failed = false
        message = isDirty ? "Есть несохранённые цены." : "Изменений нет."
    }

    func load(_ file: URL?, project: ProjectLocation, template: String, stores: [String]) {
        guard !isDirty, !isSaving else { return }
        let request = UUID()
        generation = request
        self.file = file
        self.template = template
        self.stores = stores
        failed = false
        snapshot = nil
        guard let file else {
            isLoading = false
            message = "Выберите таблицу на первом шаге."
            return
        }
        isLoading = true
        message = "Загружаю предпросмотр…"
        Task {
            do {
                let result = try await execute(file: file, project: project)
                guard generation == request else { return }
                snapshot = result
                message = "Оформление файла Excel сохраняется."
            } catch {
                guard generation == request else { return }
                failed = true
                message = error.localizedDescription
            }
            if generation == request { isLoading = false }
        }
    }

    func save(project: ProjectLocation) async -> Bool {
        guard !isSaving else { return false }
        guard isDirty else { return true }
        guard let file, let snapshot else { return false }
        isSaving = true
        defer { isSaving = false }
        do {
            let changes = PriceChanges(fingerprint: snapshot.fingerprint,
                edits: edits.sorted { $0.key < $1.key }.map { PriceEdit(row: $0.key, value: $0.value) })
            let json = String(decoding: try JSONEncoder().encode(changes), as: UTF8.self)
            self.snapshot = try await execute(file: file, project: project, changes: json)
            edits = [:]
            failed = false
            message = "Цены сохранены. Резервная копия создана."
            return true
        } catch {
            failed = true
            message = error.localizedDescription
            return false
        }
    }

    func discard(project: ProjectLocation, reload: Bool = true) {
        guard !isSaving else { return }
        edits = [:]
        if reload { load(file, project: project, template: template, stores: stores) }
    }

    private func execute(file: URL, project: ProjectLocation, changes: String? = nil) async throws -> PreviewSnapshot {
        var args = ["workbook_preview.py", "--file", file.path, "--template", template,
                    "--stores", stores.joined(separator: ",")]
        if let changes { args += ["--changes", changes] }
        guard let command = project.command(args), let directory = project.directory else {
            throw NSError(domain: "Preview", code: 1, userInfo: [NSLocalizedDescriptionKey: "Не найдены скрипты предпросмотра."])
        }
        let process = Process()
        process.executableURL = command.executable
        process.arguments = command.arguments
        process.currentDirectoryURL = directory
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        process.environment = env
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        try process.run()
        var output = ""
        // Читаем одновременно с процессом: большие таблицы не блокируются на заполненном stdout.
        for try await line in pipe.fileHandleForReading.bytes.lines { output += line + "\n" }
        process.waitUntilExit()
        let data = Data(output.utf8)
        if let error = try? JSONDecoder().decode(PreviewFailure.self, from: data) {
            throw NSError(domain: "Preview", code: 2, userInfo: [NSLocalizedDescriptionKey: error.error])
        }
        guard process.terminationStatus == 0 else {
            throw NSError(domain: "Preview", code: 3, userInfo: [NSLocalizedDescriptionKey: "Не удалось прочитать таблицу. Проверьте файл и права доступа."])
        }
        return try JSONDecoder().decode(PreviewSnapshot.self, from: data)
    }
}
