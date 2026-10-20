// Рисует иконку приложения в .iconset: градиентный «сквиркл» с символом графика.
// Использование: swift make_icon.swift <путь/AppIcon.iconset>
import AppKit

let out = URL(filePath: CommandLine.arguments[1])
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func render(_ size: Int) -> Data {
    let s = CGFloat(size)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    // Отступ как у системных иконок macOS (~10%), скругление ~22%
    let inset = s * 0.1
    let rect = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
    let path = NSBezierPath(roundedRect: rect, xRadius: rect.width * 0.225, yRadius: rect.width * 0.225)

    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.25)
    shadow.shadowOffset = NSSize(width: 0, height: -s * 0.012)
    shadow.shadowBlurRadius = s * 0.03
    shadow.set()
    NSColor.white.setFill()
    path.fill()
    NSShadow().set()

    let gradient = NSGradient(colors: [
        NSColor(srgbRed: 0.16, green: 0.78, blue: 0.56, alpha: 1),
        NSColor(srgbRed: 0.05, green: 0.42, blue: 0.86, alpha: 1),
    ])!
    gradient.draw(in: path, angle: -60)

    let config = NSImage.SymbolConfiguration(pointSize: rect.width * 0.5, weight: .semibold)
        .applying(.init(paletteColors: [.white]))
    if let symbol = NSImage(systemSymbolName: "chart.line.uptrend.xyaxis", accessibilityDescription: nil)?
        .withSymbolConfiguration(config) {
        let sz = symbol.size
        let origin = NSPoint(x: rect.midX - sz.width / 2, y: rect.midY - sz.height / 2)
        symbol.draw(in: NSRect(origin: origin, size: sz))
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    try render(base).write(to: out.appending(path: "icon_\(base)x\(base).png"))
    try render(base * 2).write(to: out.appending(path: "icon_\(base)x\(base)@2x.png"))
}
print("ok")
