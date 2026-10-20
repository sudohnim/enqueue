# Releasing Enqueue with fastlane

The builds are `bin/release android` and `bin/release desktop`, which only build; these lanes wrap them with what a store upload needs, so uploading is always its own step.
The front door is `bin/deploy` (Dequeue's): `bin/deploy android dev` releases to Play internal testing, `bin/deploy android prod` to Play production after asking, `bin/deploy desktop` makes the notarized `.dmg`.
Engineering detail on the builds themselves is in AGENTS.md ("The Android release build", "The Mac app bundle").

## Once per machine

```sh
bundle install          # gems go to vendor/bundle (gitignored)
```

Set a UTF-8 locale (`export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8`) or fastlane warns on every run.

**Android.**
`desktop/gen/android/key.properties` and `release.keystore` sign the bundle with the upload key (Play App Signing holds the app key).
Put a Play service account JSON key at `desktop/play-store-svc.json` (gitignored), or point `PLAY_JSON_KEY` at one elsewhere.
The service account must be invited to the Enqueue app in Play Console (Users and permissions, with release rights) before any lane can read or upload; until then Play answers "The caller does not have permission".
The key is Dequeue's `google-play@sudohnim-play-billing` service account, which has account-wide Play Console access; copy Dequeue's `frontend/play-store-svc.json` there.
Never commit the key.

**Mac.**
The Developer ID Application certificate in the login keychain, and a notarytool profile made once:

```sh
xcrun notarytool store-credentials enqueue-notary --apple-id <you> --team-id 572NMYL3ZG
```

## Lanes

| Lane | What it does |
| --- | --- |
| `bundle exec fastlane android dev` (`bin/deploy android dev`) | signed `.aab` with a fresh versionCode, released to the internal testing track (completed, so testers get it) |
| `bundle exec fastlane android prod` (`bin/deploy android prod`) | the same, released to production; `ANDROID_PROD_ROLLOUT=0.1` makes it a staged rollout to 10% |
| `bundle exec fastlane android next_code` | prints the versionCode the next upload would use; reads Play, changes nothing |
| `bundle exec fastlane mac release` (`bin/deploy desktop`) | Developer ID signed, notarized and stapled `.dmg` (outside the App Store; nothing is uploaded) |

The Mac lane takes `APPLE_SIGNING_IDENTITY` and `NOTARY_PROFILE` when set, else `Developer ID Application: Sudohnim, LLC (572NMYL3ZG)` and `enqueue-notary`.
The `.dmg` lands in `desktop/target/release/bundle/dmg/`.

## Version codes

Play refuses a versionCode it has already seen.
Tauri derives one from `tauri.conf.json`'s version (0.3.0 gives 3000), so every build of a version gets the same code.
The Android lanes ask Play for every code it has (uploaded bundles and APKs, and every track), take the larger of that and the code this checkout last built (`desktop/gen/android/app/tauri.properties`, which Tauri rewrites each build and git ignores), and add one.
The local half matters because Play reserves a code the moment a bundle is uploaded, even when the upload fails, and never lists it.
`bin/release android` takes the code as `ANDROID_VERSION_CODE` and merges it into the Tauri config for that build only, so nothing in the repo changes per release.
The lane refuses to upload if the built code differs from the one it asked for.

## iOS

No lane yet; the iPhone app is on `feature/ios`.
The Fastfile's header says how one goes in, after Dequeue's `platform :ios`.
