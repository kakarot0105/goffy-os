plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "dev.goffy.os"
    compileSdk = 36
    testBuildType = providers.gradleProperty("goffy.testBuildType").orElse("debug").get()

    defaultConfig {
        applicationId = "dev.goffy.os"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
        buildConfigField("boolean", "GOFFY_LOCAL_MODEL_DEVELOPER_RUNTIME_ALLOWED", "false")
        buildConfigField("boolean", "GOFFY_LOCAL_MODEL_USER_ENABLED_DEFAULT", "false")
        buildConfigField("String", "GOFFY_LOCAL_MODEL_FILE_NAME", "\"router.litertlm\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
        create("modelDebug") {
            initWith(getByName("debug"))
            matchingFallbacks += listOf("debug")
            applicationIdSuffix = ".model"
            versionNameSuffix = "-model"
            buildConfigField("boolean", "GOFFY_LOCAL_MODEL_DEVELOPER_RUNTIME_ALLOWED", "true")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    sourceSets.getByName("test").resources.directories.add(
        "../../protocol/fixtures",
    )
    sourceSets.getByName("test").resources.directories.add(
        "../../shared/fixtures",
    )
}

dependencies {
    val cameraxVersion = "1.6.1"
    val composeBom = platform("androidx.compose:compose-bom:2026.06.00")
    val litertLmVersion = "0.14.0"

    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    implementation("androidx.camera:camera-view:$cameraxVersion")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    implementation("com.google.android.gms:play-services-mlkit-text-recognition:19.0.1")
    implementation("com.squareup.okhttp3:okhttp:5.4.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver3:5.4.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
    testImplementation("org.robolectric:robolectric:4.16")

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("com.google.ai.edge.litertlm:litertlm-android:$litertLmVersion")
    add("modelDebugImplementation", "com.google.ai.edge.litertlm:litertlm-android:$litertLmVersion")
    add("modelDebugImplementation", "org.tensorflow:tensorflow-lite-task-text:0.4.4")
    androidTestImplementation("junit:junit:4.13.2")
}
