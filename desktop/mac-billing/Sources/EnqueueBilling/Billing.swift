import Foundation
import RevenueCat

// The Mac twin of plugins/tauri-plugin-billing (the iPhone's): the RevenueCat user is
// the Enqueue sync account, so a purchase reaches the relay through RevenueCat's webhook.
// Each function blocks its caller (a Rust worker thread, never the main thread) until
// RevenueCat answers, and returns JSON in the iPhone plugin's shapes as a C string the
// caller frees (lib.rs mac_billing).

// RevenueCat's public App Store key for Enqueue (the Mac shares the iPhone's app record).
private let apiKey = "appl_IOBeeCBqzbGDuFCRXfXlSkcBGjN"
private let pro = "pro"

private final class Box: @unchecked Sendable { var value: [String: Any] = [:] }

private func answer(_ work: @escaping @Sendable () async -> [String: Any]) -> UnsafeMutablePointer<CChar> {
  let done = DispatchSemaphore(value: 0)
  let box = Box()
  Task.detached {
    box.value = await work()
    done.signal()
  }
  done.wait()
  let data = (try? JSONSerialization.data(withJSONObject: box.value)) ?? Data("{}".utf8)
  return strdup(String(decoding: data, as: UTF8.self))!
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

private func fail(_ error: Error) -> [String: Any] {
  ["ok": false, "reason": "error", "message": error.localizedDescription]
}

private func period(_ product: StoreProduct) -> Any {
  guard let p = product.subscriptionPeriod else { return NSNull() }
  let unit: String
  switch p.unit {
  case .day: unit = "D"
  case .week: unit = "W"
  case .month: unit = "M"
  case .year: unit = "Y"
  @unknown default: unit = "M"
  }
  return "P\(p.value)\(unit)"
}

@_cdecl("enqueue_billing_start")
public func billingStart(account: UnsafePointer<CChar>) -> UnsafeMutablePointer<CChar> {
  let id = String(cString: account)
  return answer {
    do {
      if !Purchases.isConfigured {
        Purchases.configure(with: Configuration.Builder(withAPIKey: apiKey).with(appUserID: id).build())
        return state(try await Purchases.shared.customerInfo())
      }
      if Purchases.shared.appUserID == id {
        return state(try await Purchases.shared.customerInfo())
      }
      return state(try await Purchases.shared.logIn(id).customerInfo)
    } catch {
      return fail(error)
    }
  }
}

@_cdecl("enqueue_billing_offerings")
public func billingOfferings() -> UnsafeMutablePointer<CChar> {
  answer {
    guard Purchases.isConfigured else { return ["ok": false, "reason": "not_started"] }
    do {
      let packages = (try await Purchases.shared.offerings().current?.availablePackages ?? []).map {
        [
          "id": $0.identifier,
          "title": $0.storeProduct.localizedTitle,
          "price": $0.storeProduct.localizedPriceString,
          "period": period($0.storeProduct),
        ] as [String: Any]
      }
      return ["ok": true, "packages": packages]
    } catch {
      return fail(error)
    }
  }
}

@_cdecl("enqueue_billing_purchase")
public func billingPurchase(package: UnsafePointer<CChar>) -> UnsafeMutablePointer<CChar> {
  let wanted = String(cString: package)
  return answer {
    guard Purchases.isConfigured else { return ["ok": false, "reason": "not_started"] }
    do {
      let offering = try await Purchases.shared.offerings().current
      guard let pkg = offering?.availablePackages.first(where: { $0.identifier == wanted }) else {
        return ["ok": false, "reason": "no_package"]
      }
      let result = try await Purchases.shared.purchase(package: pkg)
      return result.userCancelled ? ["ok": false, "reason": "cancelled"] : state(result.customerInfo)
    } catch let err as ErrorCode where err == .purchaseCancelledError {
      return ["ok": false, "reason": "cancelled"]
    } catch {
      return fail(error)
    }
  }
}

@_cdecl("enqueue_billing_restore")
public func billingRestore() -> UnsafeMutablePointer<CChar> {
  answer {
    guard Purchases.isConfigured else { return ["ok": false, "reason": "not_started"] }
    do { return state(try await Purchases.shared.restorePurchases()) } catch { return fail(error) }
  }
}
