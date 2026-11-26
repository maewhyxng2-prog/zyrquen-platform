# RealityCheck Android client

Native Android application built with Kotlin and Jetpack Compose.

## Build a debug APK

Requirements:
- JDK 17
- Gradle 8.11.1
- Android SDK Platform 35 and Build Tools installed

From the repository root:

```bash
gradle -p android :app:assembleDebug
```

APK output:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

Install on a connected device:

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

## Connect to a real backend

Open the app and enter the deployed API origin ending in `/`, for example your own HTTPS API host. The app rejects non-HTTPS API origins. Sign in using an account already registered with the repository's FastAPI authentication service.

The app reads live health/workflow data and calls the repository's `/v1/native-ai/infer` endpoint. It does not contain seeded runs or demo credentials.

## Current implementation boundary

This initial APK slice provides:
- HTTPS backend configuration;
- existing FastAPI login, current-user validation, and logout;
- encrypted local bearer-token storage backed by Android Keystore;
- live backend health and workflow-run reads;
- Native AI assistant using the existing ZYRQUEN runtime.

RestoreProof execution controls are intentionally disabled until an isolated PostgreSQL restore worker and its evidence API are implemented and tested. The app must not claim restore success based on AI output or the checksum-only verifier.
