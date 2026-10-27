import Foundation
import RevenueCat
import Tauri
import UIKit
import WebKit

/// Enqueue Pro through the App Store, by RevenueCat (Billing.kt's twin).
///
/// The RevenueCat user IS the Enqueue sync account (its id, from the relay's
/// /account/plan), so a purchase reaches the relay through RevenueCat's webhook and every
/// device of the account sees Pro. Nothing here decides what Pro allows: the relay does.
/// Every command answers in Billing.kt's shapes: {ok, pro, expires, willRenew, manage},
/// {ok, packages: [{id, type, title, price, period}]}, or {ok: false, reason}.
class StartArgs: Decodable {
  let accountId: String
}

class PurchaseArgs: Decodable {
  let packageId: String
}

class BillingPlugin: Plugin {
  // RevenueCat's public App Store key for Enqueue. Public by design: it can only read
  // offerings and start purchases; the secret keys never ship.
  private let apiKey = "appl_IOBeeCBqzbGDuFCRXfXlSkcBGjN"
  private let pro = "pro"

  @objc public func start(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(StartArgs.self)
    Task {
      do {
        // An empty account is the sample library: an anonymous RevenueCat user, which
        // the Enqueue sync account takes over (logIn) once the phone links.
        let account = args.accountId.isEmpty ? nil : args.accountId
        if !Purchases.isConfigured {
          Purchases.configure(with: Configuration.Builder(withAPIKey: apiKey).with(appUserID: account).build())
          invoke.resolve(state(try await Purchases.shared.customerInfo()))
        } else if account == nil || Purchases.shared.appUserID == args.accountId {
          invoke.resolve(state(try await Purchases.shared.customerInfo()))
        } else {
          let (info, _) = try await Purchases.shared.logIn(args.accountId)
          invoke.resolve(state(info))
        }
      } catch {
        invoke.resolve(fail("error", error))
      }
    }
  }

  @objc public func status(_ invoke: Invoke) {
    guard Purchases.isConfigured else { return invoke.resolve(["ok": false, "reason": "not_started"]) }
    Task {
      do { invoke.resolve(state(try await Purchases.shared.customerInfo())) } catch { invoke.resolve(fail("error", error)) }
    }
  }

  @objc public func offerings(_ invoke: Invoke) {
    guard Purchases.isConfigured else { return invoke.resolve(["ok": false, "reason": "not_started"]) }
    Task {
      do {
        let offerings = try await Purchases.shared.offerings()
        let packages = (offerings.current?.availablePackages ?? []).map(describe)
        invoke.resolve(["ok": true, "packages": packages])
      } catch {
        invoke.resolve(fail("error", error))
      }
    }
  }

  @objc public func purchase(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(PurchaseArgs.self)
    guard Purchases.isConfigured else { return invoke.resolve(["ok": false, "reason": "not_started"]) }
    Task {
      do {
        let offerings = try await Purchases.shared.offerings()
        guard let pkg = offerings.current?.availablePackages.first(where: { $0.identifier == args.packageId }) else {
          return invoke.resolve(["ok": false, "reason": "no_package"])
        }
        let result = try await Purchases.shared.purchase(package: pkg)
        if result.userCancelled {
          invoke.resolve(["ok": false, "reason": "cancelled"])
        } else {
          invoke.resolve(state(result.customerInfo))
        }
      } catch let err as ErrorCode where err == .purchaseCancelledError {
        invoke.resolve(["ok": false, "reason": "cancelled"])
      } catch {
        invoke.resolve(fail("error", error))
      }
    }
  }

  @objc public func restore(_ invoke: Invoke) {
    guard Purchases.isConfigured else { return invoke.resolve(["ok": false, "reason": "not_started"]) }
    Task {
      do { invoke.resolve(state(try await Purchases.shared.restorePurchases())) } catch { invoke.resolve(fail("error", error)) }
    }
  }

  private func describe(_ pkg: Package) -> [String: Any] {
    let product = pkg.storeProduct
    var period: Any = NSNull()
    if let p = product.subscriptionPeriod {
      let unit: String
      switch p.unit {
      case .day: unit = "D"
      case .week: unit = "W"
      case .month: unit = "M"
      case .year: unit = "Y"
      @unknown default: unit = "M"
      }
      period = "P\(p.value)\(unit)"
    }
    return [
      "id": pkg.identifier,
      "type": String(describing: pkg.packageType).uppercased(),
      "title": product.localizedTitle,
      "price": product.localizedPriceString,
      "period": period,
    ]
  }

  private func state(_ info: CustomerInfo) -> [String: Any] {
    let entitlement = info.entitlements[pro]
    return [
      "ok": true,
      "pro": entitlement?.isActive == true,
      "expires": entitlement?.expirationDate.map { Int($0.timeIntervalSince1970 * 1000) } as Any? ?? NSNull(),
      "willRenew": entitlement?.willRenew == true,
      "manage": info.managementURL?.absoluteString as Any? ?? NSNull(),
    ]
  }

  private func fail(_ reason: String, _ error: Error) -> [String: Any] {
    ["ok": false, "reason": reason, "message": error.localizedDescription]
  }
}

@_cdecl("init_plugin_billing")
func initPlugin() -> Plugin {
  return BillingPlugin()
}
