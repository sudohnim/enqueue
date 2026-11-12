// swift-tools-version:5.9
// Enqueue Pro through the Mac App Store, by RevenueCat: linked into the desktop shell by
// build.rs (swift-rs) only for the App Store build (`--features mas`).
import PackageDescription

let package = Package(
  name: "EnqueueBilling",
  platforms: [.macOS(.v12)],
  products: [
    .library(name: "EnqueueBilling", type: .static, targets: ["EnqueueBilling"])
  ],
  dependencies: [
    .package(url: "https://github.com/RevenueCat/purchases-ios-spm.git", from: "5.0.0"),
  ],
  targets: [
    .target(
      name: "EnqueueBilling",
      dependencies: [
        .product(name: "RevenueCat", package: "purchases-ios-spm"),
      ])
  ]
)
