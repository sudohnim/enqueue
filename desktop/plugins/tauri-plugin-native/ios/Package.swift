// swift-tools-version:5.9
import PackageDescription

let package = Package(
  name: "tauri-plugin-native",
  platforms: [.iOS(.v16)],
  products: [
    .library(name: "tauri-plugin-native", type: .static, targets: ["tauri-plugin-native"])
  ],
  dependencies: [
    .package(name: "Tauri", path: "../.tauri/tauri-api")
  ],
  targets: [
    .target(
      name: "tauri-plugin-native",
      dependencies: [.byName(name: "Tauri")],
      path: "Sources")
  ]
)
