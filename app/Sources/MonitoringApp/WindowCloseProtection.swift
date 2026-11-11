import AppKit
import SwiftUI

/// Сохраняет штатного делегата SwiftUI и добавляет защиту закрытия с несохранёнными ценами.
struct WindowCloseProtection: NSViewRepresentable {
    let model: AppModel

    func makeNSView(context: Context) -> Bridge {
        let view = Bridge()
        view.guardDelegate.model = model
        return view
    }

    func updateNSView(_ view: Bridge, context: Context) { view.guardDelegate.model = model }

    final class Bridge: NSView {
        let guardDelegate = CloseDelegate()
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard let window, window.delegate !== guardDelegate else { return }
            guardDelegate.original = window.delegate
            window.delegate = guardDelegate
        }
    }

    final class CloseDelegate: NSObject, NSWindowDelegate {
        weak var model: AppModel?
        nonisolated(unsafe) var original: NSWindowDelegate?
        private var permitted = false

        func windowShouldClose(_ sender: NSWindow) -> Bool {
            if permitted { return original?.windowShouldClose?(sender) ?? true }
            guard let model, model.needsCloseCheck else { return original?.windowShouldClose?(sender) ?? true }
            Task {
                if await model.prepareToClose() {
                    permitted = true
                    sender.performClose(nil)
                    permitted = false
                }
            }
            return false
        }

        override nonisolated func responds(to selector: Selector!) -> Bool {
            super.responds(to: selector) || original?.responds(to: selector) == true
        }

        override nonisolated func forwardingTarget(for selector: Selector!) -> Any? {
            original?.responds(to: selector) == true ? original : super.forwardingTarget(for: selector)
        }
    }
}
