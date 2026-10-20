import Foundation
import Observation

/// Где лежат скрипты мониторинга и рабочие файлы.
/// Сборка .dmg: скрипты встроены в приложение, рабочие файлы — в ~/Library/Application Support/Мониторинг цен.
/// Иначе — папка проекта (run.py, .venv): рядом с приложением, в сохранённых настройках или ~/Developer/monitoring.
@Observable
final class ProjectLocation {
    private static let defaultsKey = "projectDirectory"

    private(set) var directory: URL?

    /// Скрипты, встроенные в приложение (сборка .dmg).
    let bundledTools: URL? = {
        guard let url = Bundle.main.resourceURL?.appending(path: "tools/monitoring-tools/monitoring-tools"),
              FileManager.default.isExecutableFile(atPath: url.path) else { return nil }
        return url
    }()

    private static let scriptTools = [
        "run.py": "run", "fill_links.py": "fill_links", "nosimo.py": "nosimo", "make_links_template.py": "make_links",
    ]

    init() {
        if bundledTools != nil {
            let support = URL.applicationSupportDirectory.appending(path: "Мониторинг цен")
            try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
            directory = support
            return
        }
        let candidates: [URL?] = [
            Bundle.main.bundleURL.deletingLastPathComponent(),
            UserDefaults.standard.url(forKey: Self.defaultsKey),
            URL.homeDirectory.appending(path: "Developer/monitoring"),
        ]
        directory = candidates.compactMap(\.self).first(where: Self.isProject)
    }

    /// Последний сохранённый результат — для кнопки «Открыть последний результат».
    var latestResult: URL? {
        guard let url = UserDefaults.standard.url(forKey: "lastResult"),
              FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url
    }

    /// Как запустить скрипт: встроенный monitoring-tools или python из .venv папки проекта.
    /// arguments[0] — имя скрипта («run.py» и т.п.).
    func command(_ arguments: [String]) -> (executable: URL, arguments: [String])? {
        guard let script = arguments.first, let dir = directory else { return nil }
        if let tools = bundledTools, let tool = Self.scriptTools[script] {
            return (tools, [tool] + arguments.dropFirst())
        }
        return (dir.appending(path: ".venv/bin/python"), arguments)
    }

    /// Руководство пользователя: внутри приложения или в папке проекта.
    var helpFile: URL? {
        let url = bundledTools != nil
            ? Bundle.main.resourceURL?.appending(path: "docs/guide.html")
            : directory?.appending(path: "docs/guide.html")
        return url.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil }
    }

    @discardableResult
    func choose(_ url: URL) -> Bool {
        guard Self.isProject(url) else { return false }
        directory = url
        UserDefaults.standard.set(url, forKey: Self.defaultsKey)
        return true
    }

    static func isProject(_ url: URL) -> Bool {
        let fm = FileManager.default
        return fm.fileExists(atPath: url.appending(path: "run.py").path)
            && fm.isExecutableFile(atPath: url.appending(path: ".venv/bin/python").path)
    }
}
