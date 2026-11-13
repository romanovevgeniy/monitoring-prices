import AppKit
import SwiftUI

struct GuidedWorkflowView: View {
    let model: AppModel
    let runner: MonitorRunner
    private let names = ["Таблица", "Наши цены", "Сбор цен"]
    private let titles = ["Выберите таблицу и источник", "Проверьте наши цены", "Всё готово к сбору"]
    private let hints = ["Выберите файл, шаблон и папку для результатов.",
                         "Меняйте колонку НОСИМО прямо в предпросмотре. Остальные ячейки защищены.",
                         "Проверьте настройки и начните сбор цен конкурентов."]

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Label("Мониторинг цен", systemImage: "chart.line.uptrend.xyaxis").font(.headline)
                Spacer()
                Button("Справка", systemImage: "questionmark.circle") { model.openHelp() }
                    .buttonStyle(.borderless)
            }
            VStack(alignment: .leading, spacing: 7) {
                Text(model.isSpbTemplate ? "ТВ и акустика · Санкт-Петербург" : model.detectedTable ?? "Новый запуск")
                    .font(.caption).foregroundStyle(.secondary)
                Text(runner.isBusy ? "Выполняем мониторинг" : model.guidedStep == 2 && !runner.savedFiles.isEmpty && runner.mode == .prices ? "Результаты мониторинга" : titles[model.guidedStep])
                    .font(.system(size: 30, weight: .bold)).tracking(-0.6)
                Text(hints[model.guidedStep]).foregroundStyle(.secondary)
            }
            HStack(spacing: 10) {
                ForEach(0..<3, id: \.self) { index in
                    Button { model.requestStep(index) } label: {
                        HStack(spacing: 9) {
                            Text("\(index + 1)")
                                .font(.callout.monospacedDigit())
                                .frame(width: 24, height: 24)
                                .foregroundStyle(model.guidedStep == index ? .white : .secondary)
                                .background(model.guidedStep == index ? Color.accentColor : Color.primary.opacity(0.06), in: .circle)
                            Text(names[index]).fontWeight(model.guidedStep == index ? .semibold : .regular)
                            Spacer(minLength: 0)
                        }.padding(12)
                        .frame(maxWidth: .infinity)
                        .background(model.guidedStep == index ? Color(nsColor: .controlBackgroundColor) : .clear, in: .rect(cornerRadius: 9))
                        .overlay { RoundedRectangle(cornerRadius: 9).strokeBorder(model.guidedStep == index ? Color.accentColor : Color.primary.opacity(0.1)) }
                    }
                    .buttonStyle(.plain)
                    .disabled(runner.isBusy || model.preview.isSaving || (index > 0 && !model.canStartPrices))
                    .accessibilityLabel("Шаг \(index + 1): \(names[index])")
                    .accessibilityValue(model.guidedStep == index ? "Выбран" : "")
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(alignment: .top, spacing: 24) {
                        instructions.frame(width: 280, alignment: .topLeading)
                        PricePreviewPanel(model: model, runner: runner).frame(minHeight: 340, maxHeight: 420)
                    }
                    if model.guidedStep == 2, runner.phase != .idle {
                        StatusSection(runner: runner)
                        if !runner.feed.isEmpty || !runner.stores.isEmpty {
                            DisclosureGroup("Журнал и магазины", isExpanded: Binding(get: { model.showJournal }, set: { model.showJournal = $0 })) {
                                VStack(spacing: 12) {
                                    if !runner.stores.isEmpty { StoresCard(stores: runner.stores) }
                                    FeedCard(feed: runner.feed).frame(height: 150)
                                }.padding(.top, 10)
                            }
                        }
                    }
                }.padding(.vertical, 2)
            }
            Divider()
            HStack {
                Text(model.canStartPrices ? "Оформление Excel сохраняется." : "Выберите таблицу, папку и хотя бы один магазин.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Назад") { model.requestStep(model.guidedStep - 1) }
                    .disabled(model.guidedStep == 0 || runner.isBusy || model.preview.isSaving)
                Button(primaryTitle, systemImage: runner.isBusy ? "stop.fill" : model.guidedStep < 2 ? "arrow.right" : "play.fill") {
                    if runner.isBusy { runner.stop() }
                    else if model.guidedStep < 2 { model.requestStep(model.guidedStep + 1) }
                    else { model.start() }
                }
                .buttonStyle(.borderedProminent).controlSize(.large)
                .disabled(runner.phase == .stopping || (!runner.isBusy && !model.canStartPrices))
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .background(Color(nsColor: .windowBackgroundColor))
        .background(WindowCloseProtection(model: model))
    }

    private var primaryTitle: String {
        if runner.phase == .stopping { return "Останавливаю…" }
        if runner.isBusy { return "Остановить" }
        return ["Далее: наши цены", "Далее: сбор цен", "Собрать цены"][model.guidedStep]
    }

    @ViewBuilder
    private var instructions: some View {
        switch model.guidedStep {
        case 0:
            SetupCard(model: model, disabled: runner.isBusy)
        case 1:
            VStack(alignment: .leading, spacing: 18) {
                Text("Наши цены НОСИМО").font(.title3.bold())
                Text("Измените нужные цены справа. Перед переходом на следующий шаг они сохранятся с резервной копией.")
                    .fixedSize(horizontal: false, vertical: true)
                Button("Обновить с galaxystore", systemImage: "arrow.clockwise") { model.updateNosimo() }
                    .disabled(!model.canStart)
                if let source = model.sourceFile {
                    Button("Открыть всю таблицу", systemImage: "tablecells") { NSWorkspace.shared.open(source) }
                }
                Label("Цены конкурентов защищены от ручного изменения.", systemImage: "lock.shield")
                    .font(.caption).foregroundStyle(.secondary)
            }
        default:
            VStack(alignment: .leading, spacing: 18) {
                reviewField("Таблица", model.sourceFile?.lastPathComponent ?? "Не выбрана")
                reviewField("Источник", model.isSpbTemplate ? "samsungstore · Санкт-Петербург" : model.availableStores.filter { model.selectedStores.contains($0.key) }.map(\.name).joined(separator: ", "))
                reviewField("Результат", model.rootDirectory?.path ?? "Выберите папку")
                Label("Исходная таблица сохраняется. При ошибке сайта прежние цены остаются в результате, причина попадает в журнал.", systemImage: "checkmark.shield")
                    .font(.caption).foregroundStyle(.secondary)
                if !(model.preview.snapshot?.retryPairs.isEmpty ?? true), !runner.isBusy {
                    Button("Повторить ошибки (\(model.preview.snapshot?.retryPairs.count ?? 0))", systemImage: "arrow.clockwise") {
                        model.retryFailed()
                    }.disabled(!model.canStartPrices)
                }
                if let latest = model.project.latestResult {
                    Button("Открыть последний результат", systemImage: "tablecells") { NSWorkspace.shared.open(latest) }
                }
            }
        }
    }

    private func reviewField(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct PricePreviewPanel: View {
    let model: AppModel
    let runner: MonitorRunner

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Предпросмотр таблицы").font(.callout).foregroundStyle(.secondary)
                    Spacer()
                    if let data = model.preview.snapshot { Text("\(data.count) товаров").font(.caption).foregroundStyle(.secondary) }
                    if model.preview.isLoading || model.preview.isSaving { ProgressView().controlSize(.small) }
                }
                if let data = model.preview.snapshot {
                    Text("Обновлено полностью: \(data.summary.updated) · Дешевле: \(data.summary.cheaper) · Товаров с ошибками: \(data.summary.errors)")
                        .font(.caption).fixedSize(horizontal: false, vertical: true)
                    Text("Неподтверждённые: \(data.summary.unconfirmed) · Максимальная разница: \(data.summary.maxDifference.formatted(.number.precision(.fractionLength(0)))) ₽")
                        .font(.caption).foregroundStyle(.secondary)
                    Picker("Фильтр результатов", selection: Binding(get: { model.preview.filter }, set: { model.preview.filter = $0 })) {
                        Text("Все товары").tag("all")
                        Text("Конкурент дешевле").tag("cheaper")
                        Text("Ошибки").tag("errors")
                        Text("Неподтверждённые цены").tag("unconfirmed")
                    }.pickerStyle(.menu)
                    ScrollView([.horizontal, .vertical]) {
                        VStack(alignment: .leading, spacing: 0) {
                            HStack(spacing: 0) {
                                Text("Артикул").frame(width: 175, alignment: .leading)
                                ForEach(data.columns) { column in Text(column.name).frame(width: 155, alignment: .trailing) }
                                Text("НОСИМО").frame(width: 120, alignment: .trailing)
                            }
                            .font(.caption).foregroundStyle(.secondary).padding(.vertical, 12)
                            Divider()
                            if model.preview.visibleRows.isEmpty {
                                Text("Нет товаров для выбранного фильтра.").font(.caption).padding(.vertical)
                            }
                            LazyVStack(alignment: .leading, spacing: 0) {
                                ForEach(model.preview.visibleRows) { row in
                                    HStack(spacing: 0) {
                                        Text(row.article).font(.system(.callout, design: .monospaced)).frame(width: 175, alignment: .leading)
                                        ForEach(data.columns.indices, id: \.self) { index in
                                            VStack(alignment: .trailing, spacing: 4) {
                                                Text(row.prices[index]).monospacedDigit()
                                                    .foregroundStyle(row.lower[index] ? .red : .primary)
                                                Text(row.statuses[index].label).font(.caption2)
                                                    .foregroundStyle(["error", "pending", "stale", "unchecked"].contains(row.statuses[index].code) ? .orange : .secondary)
                                            }
                                            .frame(width: 155, alignment: .trailing)
                                            .help(row.statuses[index].message + "\n" + row.statuses[index].checkedAt)
                                        }
                                        if model.guidedStep == 1 && !runner.isBusy {
                                            TextField("Цена", text: Binding(get: { model.preview.value(row) }, set: { model.preview.edit(row, value: $0) }))
                                                .textFieldStyle(.roundedBorder).multilineTextAlignment(.trailing)
                                                .frame(width: 112).padding(.leading, 8)
                                                .disabled(model.preview.isSaving || model.preview.isLoading)
                                                .accessibilityLabel("Цена НОСИМО \(row.article)")
                                        } else {
                                            Text(row.baseDisplay).monospacedDigit().frame(width: 120, alignment: .trailing)
                                        }
                                    }.frame(minHeight: 58)
                                    Divider()
                                }
                            }
                        }
                    }
                } else if !model.preview.isLoading {
                    ContentUnavailableView("Нет предпросмотра", systemImage: "tablecells", description: Text(model.preview.message))
                }
                HStack(alignment: .top) {
                    Text(model.preview.message).font(.caption)
                        .foregroundStyle(model.preview.failed ? .red : .secondary)
                        .textSelection(.enabled)
                    Spacer()
                    if model.guidedStep == 1 {
                        if model.preview.isDirty {
                            Button("Отменить правки") {
                                let alert = NSAlert()
                                alert.messageText = "Отменить правки НОСИМО?"
                                alert.informativeText = "Несохранённые цены будут отброшены. Существующий файл не изменится."
                                alert.addButton(withTitle: "Отменить правки")
                                alert.addButton(withTitle: "Продолжить редактирование")
                                if alert.runModal() == .alertFirstButtonReturn { model.preview.discard(project: model.project) }
                            }.disabled(model.preview.isSaving)
                        }
                        Button("Сохранить цены") { Task { _ = await model.preview.save(project: model.project) } }
                            .disabled(!model.preview.isDirty || model.preview.isSaving)
                    }
                }
            }
        }
    }
}
