// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "MonitoringApp",
    platforms: [.macOS(.v26)],
    targets: [
        .executableTarget(
            name: "MonitoringApp",
            swiftSettings: [
                .defaultIsolation(MainActor.self),
                .enableUpcomingFeature("NonisolatedNonsendingByDefault"),
            ]
        ),
    ]
)
