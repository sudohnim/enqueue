import BackgroundTasks
import Foundation
import LocalAuthentication
import Security
import Tauri
import UIKit
import WebKit

/// The iPhone twin of MainActivity's bridge: the app lock, the vault's Face ID
/// (Biometrics.kt's shapes, {ok, reason, secret?}) and the Quick capture action.
///
/// The APP LOCK is a native cover over the window, up before the page paints, lifted by
/// Face ID or the passcode. It asks again after a minute away and hides the app in the
/// app switcher. The VAULT SECRET is 32 random bytes in a Keychain item that only the
/// current set of Face IDs or fingerprints can read; enrolling a new one makes it
/// unreadable ("invalidated"). The vault key itself never leaves Rust.
class SwitchArgs: Decodable {
  let on: Bool
}

class PromptArgs: Decodable {
  let title: String
}

class NativePlugin: Plugin {
  private let appLockKey = "enqueue.appLock"
  private let service = "com.sudohnim.enqueue.vault-bio"
  private let grace: TimeInterval = 60
  private var cover: UIView?
  private var leftAt: Date?
  private var asking = false

  private weak var webview: WKWebView?

  private var appLock: Bool {
    get { UserDefaults.standard.bool(forKey: appLockKey) }
    set { UserDefaults.standard.set(newValue, forKey: appLockKey) }
  }

  override func load(webview: WKWebView) {
    self.webview = webview
    let center = NotificationCenter.default
    center.addObserver(self, selector: #selector(quickAction), name: QuickAction.chosen, object: nil)
    center.addObserver(
      self, selector: #selector(resigning), name: UIApplication.willResignActiveNotification, object: nil)
    center.addObserver(
      self, selector: #selector(leaving), name: UIApplication.didEnterBackgroundNotification, object: nil)
    center.addObserver(
      self, selector: #selector(returning), name: UIApplication.didBecomeActiveNotification, object: nil)
    if appLock {
      DispatchQueue.main.async {
        self.showCover()
        self.unlock()
      }
    }
  }

  // ---- commands --------------------------------------------------------------------

  @objc public func status(_ invoke: Invoke) {
    invoke.resolve([
      "fingerprint": biometryState(),
      "deviceLock": deviceLockState(),
      "appLock": appLock,
      "vaultSecret": hasSecret(),
      "biometry": biometryName(),
    ])
  }

  @objc public func applock(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(SwitchArgs.self)
    if args.on && deviceLockState() != "ready" {
      return invoke.resolve(["ok": false, "reason": "none"])
    }
    let reason = args.on ? "Turn on the \(biometryName()) lock" : "Turn off the \(biometryName()) lock"
    ask(.deviceOwnerAuthentication, reason) { ok, why in
      if ok { self.appLock = args.on }
      invoke.resolve(["ok": ok, "reason": why])
    }
  }

  @objc public func create(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(PromptArgs.self)
    ask(.deviceOwnerAuthenticationWithBiometrics, args.title) { ok, why in
      guard ok else { return invoke.resolve(["ok": false, "reason": why]) }
      var bytes = [UInt8](repeating: 0, count: 32)
      guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess,
        let access = SecAccessControlCreateWithFlags(
          nil, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly, .biometryCurrentSet, nil)
      else { return invoke.resolve(["ok": false, "reason": "error"]) }
      SecItemDelete(self.query() as CFDictionary)
      var item = self.query()
      item[kSecValueData] = Data(bytes)
      item[kSecAttrAccessControl] = access
      guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else {
        return invoke.resolve(["ok": false, "reason": "error"])
      }
      invoke.resolve(["ok": true, "reason": "ok", "secret": bytes.map { String(format: "%02x", $0) }.joined()])
    }
  }

  @objc public func read(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(PromptArgs.self)
    let context = LAContext()
    context.localizedReason = args.title
    context.localizedFallbackTitle = ""
    var search = query()
    search[kSecReturnData] = true
    search[kSecUseAuthenticationContext] = context
    DispatchQueue.global(qos: .userInitiated).async {
      var out: CFTypeRef?
      let status = SecItemCopyMatching(search as CFDictionary, &out)
      let reply: JSObject
      switch status {
      case errSecSuccess:
        let hex = (out as? Data)?.map { String(format: "%02x", $0) }.joined() ?? ""
        reply = ["ok": !hex.isEmpty, "reason": hex.isEmpty ? "error" : "ok", "secret": hex]
      case errSecItemNotFound:
        reply = ["ok": false, "reason": "invalidated"]
      case errSecUserCanceled:
        reply = ["ok": false, "reason": "cancelled"]
      case errSecAuthFailed:
        reply = ["ok": false, "reason": "lockout"]
      default:
        reply = ["ok": false, "reason": "error"]
      }
      invoke.resolve(reply)
    }
  }

  /// Whether the app was opened from its Quick capture action and the page has not
  /// opened the writing page for it yet. Asking clears it.
  @objc public func quick(_ invoke: Invoke) {
    invoke.resolve(["pending": QuickAction.take()])
  }

  @objc private func quickAction() {
    webview?.evaluateJavaScript("window.__enqQuickCapture && window.__enqQuickCapture()")
  }

  @objc public func clear(_ invoke: Invoke) {
    SecItemDelete(query() as CFDictionary)
    invoke.resolve(["ok": true])
  }

  // ---- the cover -------------------------------------------------------------------

  @objc private func resigning() {
    // Hide the library from the app switcher's snapshot. A Face ID prompt also resigns
    // the app for a moment; the cover is already up then.
    if appLock && !asking { showCover() }
  }

  @objc private func leaving() {
    if leftAt == nil { leftAt = Date() }
    BackgroundSync.schedule()
  }

  @objc private func returning() {
    guard appLock, !asking else { return }
    if let left = leftAt, Date().timeIntervalSince(left) > grace {
      leftAt = nil
      unlock()
    } else if leftAt != nil || cover != nil {
      leftAt = nil
      if !needsUnlock { hideCover() }
    }
  }

  private var needsUnlock = false

  private func unlock() {
    needsUnlock = true
    showCover()
    guard deviceLockState() == "ready" else {
      // No passcode left on the phone: the lock cannot work, so it switches itself off
      // rather than shut the owner out.
      appLock = false
      needsUnlock = false
      return hideCover()
    }
    ask(.deviceOwnerAuthentication, "Unlock Enqueue") { ok, _ in
      if ok {
        self.needsUnlock = false
        self.hideCover()
      }
    }
  }

  @objc private func unlockTapped() {
    if !asking { unlock() }
  }

  private func showCover() {
    guard cover == nil, let host = manager.viewController?.view else { return }
    let view = UIView(frame: host.bounds)
    view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    view.backgroundColor = UIColor(red: 0xEE / 255, green: 0xE8 / 255, blue: 0xF6 / 255, alpha: 1)

    let raven = UIImageView(image: UIImage(named: "RavenMark"))
    raven.contentMode = .scaleAspectFit
    raven.translatesAutoresizingMaskIntoConstraints = false

    let title = UILabel()
    title.text = "Enqueue is locked"
    title.font = .systemFont(ofSize: 22, weight: .medium)
    title.textColor = UIColor(red: 0x12 / 255, green: 0x0F / 255, blue: 0x19 / 255, alpha: 1)

    var style = UIButton.Configuration.filled()
    style.title = "Unlock"
    style.baseBackgroundColor = UIColor(red: 0x60 / 255, green: 0x07 / 255, blue: 0x9F / 255, alpha: 1)
    style.baseForegroundColor = .white
    style.cornerStyle = .capsule
    style.contentInsets = NSDirectionalEdgeInsets(top: 13, leading: 40, bottom: 13, trailing: 40)
    let button = UIButton(configuration: style)
    button.addTarget(self, action: #selector(unlockTapped), for: .touchUpInside)

    let stack = UIStackView(arrangedSubviews: [raven, title, button])
    stack.axis = .vertical
    stack.alignment = .center
    stack.spacing = 20
    stack.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(stack)
    NSLayoutConstraint.activate([
      raven.widthAnchor.constraint(equalToConstant: 84),
      raven.heightAnchor.constraint(equalToConstant: 87),
      stack.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      stack.centerYAnchor.constraint(equalTo: view.centerYAnchor),
    ])
    host.addSubview(view)
    cover = view
  }

  private func hideCover() {
    cover?.removeFromSuperview()
    cover = nil
  }

  // ---- helpers ---------------------------------------------------------------------

  private func ask(_ policy: LAPolicy, _ reason: String, _ done: @escaping (Bool, String) -> Void) {
    asking = true
    LAContext().evaluatePolicy(policy, localizedReason: reason) { ok, error in
      DispatchQueue.main.async {
        self.asking = false
        guard !ok else { return done(true, "ok") }
        switch (error as? LAError)?.code {
        case .userCancel, .appCancel, .systemCancel, .userFallback: done(false, "cancelled")
        case .biometryLockout: done(false, "lockout")
        case .biometryNotEnrolled, .passcodeNotSet: done(false, "none")
        default: done(false, "error")
        }
      }
    }
  }

  private func biometryState() -> String {
    let context = LAContext()
    var error: NSError?
    if context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) { return "ready" }
    if context.biometryType == .none { return "unavailable" }
    return error?.code == LAError.biometryNotEnrolled.rawValue ? "none" : "unavailable"
  }

  private func deviceLockState() -> String {
    LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil) ? "ready" : "none"
  }

  private func biometryName() -> String {
    let context = LAContext()
    _ = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
    switch context.biometryType {
    case .faceID: return "Face ID"
    case .touchID: return "Touch ID"
    case .opticID: return "Optic ID"
    default: return "passcode"
    }
  }

  private func query() -> [CFString: Any] {
    [kSecClass: kSecClassGenericPassword, kSecAttrService: service, kSecAttrAccount: "vault"]
  }

  private func hasSecret() -> Bool {
    let context = LAContext()
    context.interactionNotAllowed = true
    var search = query()
    search[kSecUseAuthenticationContext] = context
    let status = SecItemCopyMatching(search as CFDictionary, nil)
    return status == errSecSuccess || status == errSecInteractionNotAllowed
  }
}

/// The Home Screen action "Quick capture". UIKit hands it to the scene delegate, which
/// tao owns (TaoSceneDelegate), so a subclass that also reads it takes tao's place:
/// UISceneConfiguration's delegateClass setter is wrapped before the scene connects.
enum QuickAction {
  static let type = "com.sudohnim.enqueue.capture"
  static let chosen = Notification.Name("EnqueueQuickAction")
  private static var pending = false
  private static var installed = false

  static func take() -> Bool {
    defer { pending = false }
    return pending
  }

  static func install() {
    guard !installed else { return }
    installed = true
    let sel = #selector(setter: UISceneConfiguration.delegateClass)
    guard let method = class_getInstanceMethod(UISceneConfiguration.self, sel) else { return }
    typealias Setter = @convention(c) (AnyObject, Selector, AnyClass?) -> Void
    let original = unsafeBitCast(method_getImplementation(method), to: Setter.self)
    let wrapped: @convention(block) (AnyObject, AnyClass?) -> Void = { config, given in
      original(config, sel, given.map(subclass))
    }
    method_setImplementation(method, imp_implementationWithBlock(wrapped))
  }

  private static func subclass(_ base: AnyClass) -> AnyClass {
    let name = "Enqueue" + NSStringFromClass(base)
    if let made = NSClassFromString(name) { return made }
    guard let made = objc_allocateClassPair(base, name, 0) else { return base }

    let connect = NSSelectorFromString("scene:willConnectToSession:options:")
    typealias Connect = @convention(c) (AnyObject, Selector, UIScene, UISceneSession, UIScene.ConnectionOptions) -> Void
    if let inherited = class_getMethodImplementation(base, connect) {
      let call = unsafeBitCast(inherited, to: Connect.self)
      let block: @convention(block) (AnyObject, UIScene, UISceneSession, UIScene.ConnectionOptions) -> Void = {
        this, scene, session, options in
        if options.shortcutItem?.type == type { pending = true }
        call(this, connect, scene, session, options)
      }
      class_addMethod(made, connect, imp_implementationWithBlock(block), "v@:@@@")
    }

    let perform = NSSelectorFromString("windowScene:performActionForShortcutItem:completionHandler:")
    let block: @convention(block) (AnyObject, UIWindowScene, UIApplicationShortcutItem, @escaping @convention(block) (Bool) -> Void) -> Void = {
      _, _, item, done in
      let mine = item.type == type
      if mine {
        pending = true
        NotificationCenter.default.post(name: chosen, object: nil)
      }
      done(mine)
    }
    class_addMethod(made, perform, imp_implementationWithBlock(block), "v@:@@@?")
    objc_registerClassPair(made)
    return made
  }
}

/// Sync while the app is closed: iOS wakes it now and then for a background refresh,
/// which pushes what is queued and pulls (enqueue_background_sync in lib.rs). iOS decides
/// when, from how the app is used; it is not a timer.
enum BackgroundSync {
  static let task = "com.sudohnim.enqueue.sync"

  static func register() {
    BGTaskScheduler.shared.register(forTaskWithIdentifier: task, using: nil) { task in
      schedule()
      let work = DispatchWorkItem { task.setTaskCompleted(success: enqueue_background_sync()) }
      task.expirationHandler = { work.cancel() }
      DispatchQueue.global(qos: .utility).async(execute: work)
    }
  }

  static func schedule() {
    let request = BGAppRefreshTaskRequest(identifier: task)
    request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
    try? BGTaskScheduler.shared.submit(request)
  }
}

@_silgen_name("enqueue_background_sync")
func enqueue_background_sync() -> Bool

/// Called by Rust at the start of run(), before UIKit connects the scene.
@_cdecl("enqueue_native_early")
func nativeEarly() {
  QuickAction.install()
  BackgroundSync.register()
}

@_cdecl("init_plugin_native")
func initPlugin() -> Plugin {
  return NativePlugin()
}
