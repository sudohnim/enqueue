// Enqueue's macOS Share extension: Safari, Finder, Photos or any app shares into the
// library. Everything shared is written to the inbox folder Enqueue's app group shares,
// and the engine files it into the library (share_inbox.py), whether or not it is open.

import Cocoa
import Social
import UniformTypeIdentifiers

let appGroup = "572NMYL3ZG.com.sudohnim.enqueue"

final class ShareViewController: SLComposeServiceViewController {
    private var sharedTitle = ""

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Enqueue"
        placeholder = "Why keep it? (optional)"
        let item = extensionContext?.inputItems.first as? NSExtensionItem
        sharedTitle = item?.attributedContentText?.string ?? item?.attributedTitle?.string ?? ""
    }

    override func isContentValid() -> Bool { true }

    override func didSelectPost() {
        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        let typed = contentText.trimmingCharacters(in: .whitespacesAndNewlines)
        let note = typed == sharedTitle.trimmingCharacters(in: .whitespacesAndNewlines) ? "" : typed
        collect(items) { [weak self] entries in
            do {
                try Inbox.write(entries: entries, title: self?.sharedTitle ?? "", note: note)
                self?.extensionContext?.completeRequest(returningItems: nil)
            } catch {
                self?.extensionContext?.cancelRequest(withError: error)
            }
        }
    }

    /// Each attachment as a web address, words, or a file copied into the inbox.
    private func collect(_ items: [NSExtensionItem], done: @escaping ([[String: String]]) -> Void) {
        var entries: [[String: String]] = []
        let lock = NSLock()
        let group = DispatchGroup()
        for provider in items.flatMap({ $0.attachments ?? [] }) {
            group.enter()
            load(provider) { entry in
                if let entry { lock.lock(); entries.append(entry); lock.unlock() }
                group.leave()
            }
        }
        group.notify(queue: .main) { done(entries) }
    }

    private func load(_ provider: NSItemProvider, then: @escaping ([String: String]?) -> Void) {
        if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                then(Inbox.file(at: Self.url(from: data)))
            }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.url.identifier) { data, _ in
                guard let url = Self.url(from: data) else { return then(nil) }
                then(url.isFileURL ? Inbox.file(at: url) : ["url": url.absoluteString])
            }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
            provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
                then(data.flatMap { Inbox.file(data: $0, name: provider.suggestedName ?? "Picture", type: "png") })
            }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) { data, _ in
                let text = (data as? String) ?? (data as? Data).flatMap { String(data: $0, encoding: .utf8) }
                then(text.map { ["text": $0] })
            }
        } else {
            then(nil)
        }
    }

    private static func url(from data: NSSecureCoding?) -> URL? {
        if let url = data as? URL { return url }
        if let data = data as? Data { return URL(dataRepresentation: data, relativeTo: nil) }
        if let text = data as? String { return URL(string: text) }
        return nil
    }
}

/// The folder the engine reads: one JSON file per share, beside the files it names.
enum Inbox {
    static var folder: URL? {
        guard let base = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroup) else { return nil }
        let inbox = base.appendingPathComponent("Inbox", isDirectory: true)
        try? FileManager.default.createDirectory(at: inbox, withIntermediateDirectories: true)
        return inbox
    }

    static func file(at url: URL?) -> [String: String]? {
        guard let url, let data = try? Data(contentsOf: url) else { return nil }
        return file(data: data, name: url.deletingPathExtension().lastPathComponent, type: url.pathExtension)
    }

    static func file(data: Data, name: String, type: String) -> [String: String]? {
        guard let folder else { return nil }
        let stored = UUID().uuidString + (type.isEmpty ? "" : "." + type)
        do {
            try data.write(to: folder.appendingPathComponent(stored), options: .atomic)
        } catch {
            return nil
        }
        return ["file": stored, "name": name + (type.isEmpty ? "" : "." + type)]
    }

    static func write(entries: [[String: String]], title: String, note: String) throws {
        guard let folder else { throw CocoaError(.fileNoSuchFile) }
        let share: [String: Any] = ["v": 1, "items": entries, "title": title, "note": note]
        let data = try JSONSerialization.data(withJSONObject: share)
        let name = UUID().uuidString
        let partial = folder.appendingPathComponent(name + ".part")
        try data.write(to: partial, options: .atomic)
        try FileManager.default.moveItem(at: partial, to: folder.appendingPathComponent(name + ".json"))
    }
}
