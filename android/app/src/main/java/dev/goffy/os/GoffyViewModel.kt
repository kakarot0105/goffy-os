package dev.goffy.os

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.audit.AndroidSqliteTerminalAuditStore
import dev.goffy.os.audit.ClosedTerminalAuditLoadResult
import dev.goffy.os.audit.ClosedTerminalAuditRecord
import dev.goffy.os.audit.TerminalAuditStore
import dev.goffy.os.audit.toClosedTerminalAuditRecord
import dev.goffy.os.hub.HubConfig
import dev.goffy.os.hub.HubConfigurationException
import dev.goffy.os.hub.HubCredentialLoadResult
import dev.goffy.os.hub.HubCredentialStore
import dev.goffy.os.hub.HubEndpoint
import dev.goffy.os.hub.HubGateway
import dev.goffy.os.hub.HubIdentityPin
import dev.goffy.os.hub.HubOperatorAuditException
import dev.goffy.os.hub.HubOperatorAuditGateway
import dev.goffy.os.hub.HubPairingException
import dev.goffy.os.hub.HubPairingGateway
import dev.goffy.os.hub.AndroidHubCredentialStore
import dev.goffy.os.hub.OkHttpHubGateway
import dev.goffy.os.hub.OkHttpHubOperatorAuditGateway
import dev.goffy.os.hub.OkHttpHubPairingGateway
import dev.goffy.os.hub.StoredHubCredential
import dev.goffy.os.hub.DEFAULT_HUB_OPERATOR_AUDIT_LIMIT
import dev.goffy.os.localmodel.LocalModelIntentFallback
import dev.goffy.os.localmodel.LocalModelIntentObservation
import dev.goffy.os.localmodel.AndroidLocalModelRuntimeSettingsStore
import dev.goffy.os.localmodel.LocalModelRuntimeGate
import dev.goffy.os.localmodel.LocalModelRuntimeProvider
import dev.goffy.os.localmodel.LocalModelRuntimeProviderLoader
import dev.goffy.os.localmodel.LocalModelRuntimeSettings
import dev.goffy.os.localmodel.LocalModelRuntimeSettingsLoadResult
import dev.goffy.os.localmodel.LocalModelRuntimeSettingsSaveResult
import dev.goffy.os.localmodel.LocalModelRuntimeSettingsStore
import dev.goffy.os.localmodel.LocalModelRuntimeState
import dev.goffy.os.localmodel.LocalModelRuntimeStatus
import dev.goffy.os.localmodel.MutableLocalModelRuntimeSettingsSource
import dev.goffy.os.phone.AndroidBatteryStatusSource
import dev.goffy.os.phone.AndroidDeviceInfoSource
import dev.goffy.os.phone.AndroidFlashlightSource
import dev.goffy.os.phone.AndroidSqliteNoteStore
import dev.goffy.os.phone.AndroidSystemTimerSource
import dev.goffy.os.phone.DefaultPhoneToolGateway
import dev.goffy.os.phone.PhoneToolGateway
import dev.goffy.os.phone.PhoneToolAuthorization
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.PermissionLevel
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class GoffyViewModel internal constructor(
    private val gateway: HubGateway,
    private val pairingGateway: HubPairingGateway,
    private val operatorAuditGateway: HubOperatorAuditGateway,
    private val credentialStore: HubCredentialStore,
    private val phoneGateway: PhoneToolGateway,
    private val codec: GoffyProtocolCodec,
    private val allowInsecureLoopback: Boolean,
    private val allowDevelopmentTokenConfiguration: Boolean,
    private val defaultEndpoint: String,
    deviceId: String,
    private val deviceDisplayName: String,
    private val nextTaskId: () -> UUID,
    private val approvalTtlMillis: Long = DEFAULT_APPROVAL_TTL_MILLIS,
    private val nowMillis: () -> Long = System::currentTimeMillis,
    private val auditStore: TerminalAuditStore = NoOpTerminalAuditStore,
    private val auditDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val credentialDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val localModelSettingsStore: LocalModelRuntimeSettingsStore = NoOpLocalModelRuntimeSettingsStore,
    private val localModelSettingsSource: MutableLocalModelRuntimeSettingsSource =
        MutableLocalModelRuntimeSettingsSource(),
    private val localModelRuntimeProvider: LocalModelRuntimeProvider? = null,
    private val localModelSettingsDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val localModelControlsAvailable: Boolean = false,
    private val localModelObservationExecutionAvailable: Boolean = false,
    private val localModelFallback: LocalModelIntentFallback = LocalModelRuntimeGate.goffyLiteDefault(),
    localModelStatus: LocalModelRuntimeStatus = LocalModelRuntimeStatus.disabled(),
    private val localModelStatusProvider: () -> LocalModelRuntimeStatus =
        localModelRuntimeProvider?.let { provider -> { provider.status } }
            ?: (localModelFallback as? LocalModelRuntimeGate)?.let { gate -> { gate.status } }
            ?: { localModelStatus },
) : ViewModel() {
    constructor(context: Context) : this(createAndroidGoffyDependencies(context.applicationContext))

    private constructor(dependencies: AndroidGoffyDependencies) : this(
        gateway = OkHttpHubGateway(),
        pairingGateway = OkHttpHubPairingGateway(),
        operatorAuditGateway = OkHttpHubOperatorAuditGateway(),
        credentialStore = AndroidHubCredentialStore(
            dependencies.context,
            allowInsecureLoopback = BuildConfig.DEBUG,
        ),
        phoneGateway = DefaultPhoneToolGateway(
            batteryStatusSource = AndroidBatteryStatusSource(dependencies.context),
            deviceInfoSource = AndroidDeviceInfoSource(dependencies.context),
            noteStore = AndroidSqliteNoteStore(dependencies.context),
            timerSource = AndroidSystemTimerSource(dependencies.context),
            flashlightSource = AndroidFlashlightSource(dependencies.context),
        ),
        codec = GoffyProtocolCodec(),
        allowInsecureLoopback = BuildConfig.DEBUG,
        allowDevelopmentTokenConfiguration = BuildConfig.DEBUG,
        defaultEndpoint = if (BuildConfig.DEBUG) DEBUG_HUB_ENDPOINT else RELEASE_HUB_ENDPOINT_HINT,
        deviceId = "goffy-android-${UUID.randomUUID()}",
        deviceDisplayName = android.os.Build.MODEL
            .filterNot { it.code < 0x20 || it.code == 0x7F }
            .take(80)
            .ifBlank { "GOFFY Android" },
        nextTaskId = UUID::randomUUID,
        auditStore = AndroidSqliteTerminalAuditStore(dependencies.context),
        localModelSettingsStore = dependencies.localModelSettingsStore,
        localModelSettingsSource = dependencies.localModelSettingsSource,
        localModelRuntimeProvider = dependencies.localModelRuntimeProvider,
        localModelControlsAvailable = dependencies.localModelControlsAvailable,
        localModelObservationExecutionAvailable = dependencies.localModelObservationExecutionAvailable,
    )

    private val mutableUiState = MutableStateFlow(
        GoffyUiState(
            hubEndpoint = defaultEndpoint,
            developmentTokenAllowed = allowDevelopmentTokenConfiguration,
            localModelStatus = currentLocalModelStatus(),
            localModelControlsAvailable = localModelControlsAvailable,
            localModelSettingsLoaded = false,
        ),
    )
    val uiState: StateFlow<GoffyUiState> = mutableUiState.asStateFlow()

    private var hubConfig: HubConfig? = null
    private var pairedCredentialId: UUID? = null
    private var pairedCredentialCreatedAt: Instant? = null
    private var pairedHubIdentity: HubIdentityPin? = null
    private var deviceId: String = deviceId
    private var activeJob: Job? = null
    private var linkJob: Job? = null
    private var operatorAuditJob: Job? = null
    private var localModelSettingsJob: Job? = null
    private var linkRevision = 0L
    private var pendingExecution: PendingPhoneExecution? = null
    private var approvalExpiryJob: Job? = null

    init {
        require(approvalTtlMillis > 0) { "approvalTtlMillis must be positive" }
        restoreLocalModelSettings()
        restoreHubCredential()
        observeTerminalAudit()
    }

    fun updateChargingState(charging: Boolean) {
        if (mutableUiState.value.charging == charging) return
        mutableUiState.value = mutableUiState.value.copy(charging = charging)
    }

    private fun restoreHubCredential() {
        val revision = linkRevision
        linkJob = viewModelScope.launch {
            val loaded = try {
                withContext(credentialDispatcher) { credentialStore.load() }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                if (revision == linkRevision) {
                    mutableUiState.value = mutableUiState.value.hubRestoreFailed(
                        "The local Hub credential store is unavailable. Mac access is disabled.",
                    )
                }
                return@launch
            }
            if (revision != linkRevision) return@launch
            when (loaded) {
                HubCredentialLoadResult.Empty -> {
                    pairedCredentialCreatedAt = null
                    pairedHubIdentity = null
                    mutableUiState.value = mutableUiState.value.hubRestoreEmpty()
                }
                HubCredentialLoadResult.Corrupt -> {
                    hubConfig = null
                    pairedCredentialId = null
                    pairedCredentialCreatedAt = null
                    pairedHubIdentity = null
                    mutableUiState.value = mutableUiState.value.hubRestoreFailed(
                        "The saved Hub credential was unreadable and has been removed. Pair again.",
                    )
                }
                is HubCredentialLoadResult.Loaded -> {
                    try {
                        hubConfig = loaded.credential.toHubConfig(allowInsecureLoopback)
                        pairedCredentialId = loaded.credential.credentialId
                        pairedCredentialCreatedAt = loaded.credential.createdAt
                        pairedHubIdentity = loaded.credential.hubIdentity
                        deviceId = loaded.credential.deviceId
                        mutableUiState.value = mutableUiState.value.hubConfigured(
                            loaded.credential.endpoint,
                            persistent = true,
                            hubIdentityFingerprint = loaded.credential.hubIdentity.fingerprint,
                        )
                    } catch (_: Exception) {
                        hubConfig = null
                        pairedCredentialId = null
                        pairedCredentialCreatedAt = null
                        pairedHubIdentity = null
                        runCatching {
                            withContext(credentialDispatcher) { credentialStore.clear() }
                        }
                        mutableUiState.value = mutableUiState.value.hubRestoreFailed(
                            "The saved Hub credential was invalid and has been removed. Pair again.",
                        )
                    }
                }
            }
        }
    }

    private fun observeTerminalAudit() {
        viewModelScope.launch {
            val attemptedTaskIds = mutableSetOf<UUID>()
            try {
                val loaded = withContext(auditDispatcher) { auditStore.load() }
                attemptedTaskIds += loaded.records.map(ClosedTerminalAuditRecord::taskId)
                mutableUiState.value = mutableUiState.value.auditLoaded(
                    restoredEntries = loaded.records.map(ClosedTerminalAuditRecord::toTimelineEntry),
                    discardedRecords = loaded.discardedCorruptRows,
                )
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.auditFailed()
            }

            mutableUiState.map { it.timeline.entries }.collect { entries ->
                entries.forEach { entry ->
                    if (entry.id in attemptedTaskIds) return@forEach
                    val terminalAt = entry.terminalAtEpochMillis ?: return@forEach
                    attemptedTaskIds += entry.id
                    try {
                        val record = checkNotNull(entry.toClosedTerminalAuditRecord(terminalAt)) {
                            "only terminal entries may carry terminal timestamps"
                        }
                        val stored = withContext(auditDispatcher) { auditStore.upsert(record) }
                        mutableUiState.value = mutableUiState.value.auditRecorded(
                            stored.taskId,
                            stored.recordedAtEpochMillis,
                        )
                    } catch (error: CancellationException) {
                        throw error
                    } catch (_: Exception) {
                        mutableUiState.value = mutableUiState.value.auditFailed()
                    }
                }
            }
        }
    }

    private fun restoreLocalModelSettings() {
        localModelSettingsJob = viewModelScope.launch {
            val loaded = try {
                withContext(localModelSettingsDispatcher) { localModelSettingsStore.load() }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                LocalModelRuntimeSettingsLoadResult.Unavailable
            }
            when (loaded) {
                is LocalModelRuntimeSettingsLoadResult.Loaded -> {
                    localModelSettingsSource.update(loaded.settings)
                    mutableUiState.value = mutableUiState.value.copy(
                        localModelStatus = currentLocalModelStatus(),
                        localModelControlsAvailable = localModelControlsAvailable,
                        localModelSettingsLoaded = true,
                        localModelOperationInProgress = false,
                    )
                }
                LocalModelRuntimeSettingsLoadResult.Unavailable -> {
                    localModelSettingsSource.update(LocalModelRuntimeSettings())
                    mutableUiState.value = mutableUiState.value.localModelSettingsRejected(
                        status = currentLocalModelStatus(),
                        message = "Local model settings could not be read; runtime remains off.",
                    )
                }
            }
        }
    }

    fun setLocalModelEnabled(enabled: Boolean): Boolean {
        if (!localModelControlsAvailable) {
            mutableUiState.value = mutableUiState.value.localModelSettingsRejected(
                status = currentLocalModelStatus(),
                message = "Local model runtime controls are not available in this APK.",
            )
            return false
        }
        if (!mutableUiState.value.localModelSettingsLoaded) {
            mutableUiState.value = mutableUiState.value.localModelSettingsStillLoading(
                status = currentLocalModelStatus(),
                message = "Local model settings are still loading; try again after the status settles.",
            )
            return false
        }
        if (mutableUiState.value.localModelOperationInProgress) return false
        val previous = localModelSettingsSource.snapshot()
        val requested = LocalModelRuntimeSettings(enabledByUser = enabled)
        if (previous == requested) {
            refreshLocalModelStatus()
            return true
        }
        mutableUiState.value = mutableUiState.value.localModelOperationStarted()
        localModelSettingsJob?.cancel()
        localModelSettingsJob = viewModelScope.launch {
            val saved = try {
                withContext(localModelSettingsDispatcher) { localModelSettingsStore.save(requested) }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                LocalModelRuntimeSettingsSaveResult.Failed
            }
            when (saved) {
                is LocalModelRuntimeSettingsSaveResult.Saved -> {
                    localModelSettingsSource.update(saved.settings)
                    val status = currentLocalModelStatus()
                    mutableUiState.value = mutableUiState.value.localModelSettingsApplied(
                        status = status,
                        notice = if (enabled) {
                            LocalModelNotice(
                                "Local model runtime setting enabled after verified storage.",
                                warning = false,
                            )
                        } else {
                            LocalModelNotice(
                                "Local model runtime setting disabled.",
                                warning = false,
                            )
                        },
                    )
                }
                LocalModelRuntimeSettingsSaveResult.Failed -> {
                    localModelSettingsSource.update(LocalModelRuntimeSettings())
                    mutableUiState.value = mutableUiState.value.localModelSettingsRejected(
                        status = currentLocalModelStatus(),
                        message = "Local model setting was not verified; runtime was disabled.",
                    )
                }
            }
        }
        return true
    }

    fun configureHub(endpoint: String, bearerToken: String): Boolean {
        if (!allowDevelopmentTokenConfiguration) {
            mutableUiState.value = mutableUiState.value.hubConfigurationRejected(
                "Manual bearer entry is available only in debug builds.",
            )
            return false
        }
        ++linkRevision
        linkJob?.cancel()
        operatorAuditJob?.cancel()
        val config = try {
            HubConfig.create(endpoint, bearerToken, allowInsecureLoopback)
        } catch (error: HubConfigurationException) {
            mutableUiState.value = mutableUiState.value.hubConfigurationRejected(
                error.message ?: "Hub configuration is invalid",
            )
            return false
        }
        hubConfig = config
        pairedCredentialId = null
        pairedCredentialCreatedAt = null
        pairedHubIdentity = null
        mutableUiState.value = mutableUiState.value.hubConfigured(config.endpoint)
        return true
    }

    fun pairHub(endpoint: String, challengeJson: String) {
        if (mutableUiState.value.linkOperationInProgress) return
        if (mutableUiState.value.hubConfigured) {
            mutableUiState.value = mutableUiState.value.hubConfigurationRejected(
                "Forget the current local link before pairing a different Mac.",
            )
            return
        }
        pairedCredentialId = null
        pairedCredentialCreatedAt = null
        pairedHubIdentity = null
        val parsedEndpoint = try {
            HubEndpoint.create(endpoint, allowInsecureLoopback)
        } catch (error: HubConfigurationException) {
            mutableUiState.value = mutableUiState.value.hubConfigurationRejected(
                error.message ?: "Hub endpoint is invalid.",
            )
            return
        }

        val revision = ++linkRevision
        operatorAuditJob?.cancel()
        mutableUiState.value = mutableUiState.value.hubPairingStarted(parsedEndpoint.webSocketUrl)
        linkJob = viewModelScope.launch {
            try {
                val issued = pairingGateway.redeem(
                    parsedEndpoint,
                    challengeJson,
                    deviceId,
                    deviceDisplayName,
                )
                val candidate = StoredHubCredential.create(
                    endpoint = parsedEndpoint.webSocketUrl,
                    credentialId = issued.credentialId,
                    deviceId = deviceId,
                    accessToken = issued.accessToken,
                    createdAt = issued.createdAt,
                    hubIdentity = issued.hubIdentity,
                    allowInsecureLoopback = allowInsecureLoopback,
                )
                val persisted = withContext(credentialDispatcher) {
                    credentialStore.save(candidate)
                }
                if (revision != linkRevision) return@launch
                hubConfig = persisted.toHubConfig(allowInsecureLoopback)
                pairedCredentialId = persisted.credentialId
                pairedCredentialCreatedAt = persisted.createdAt
                pairedHubIdentity = persisted.hubIdentity
                deviceId = persisted.deviceId
                mutableUiState.value = mutableUiState.value.hubConfigured(
                    persisted.endpoint,
                    persistent = true,
                    hubIdentityFingerprint = persisted.hubIdentity.fingerprint,
                )
            } catch (error: CancellationException) {
                throw error
            } catch (error: HubPairingException) {
                if (revision == linkRevision) {
                    mutableUiState.value = mutableUiState.value.hubPairingRejected(
                        error.message ?: "Pairing failed safely.",
                    )
                }
            } catch (_: Exception) {
                if (revision == linkRevision) {
                    hubConfig = null
                    pairedCredentialId = null
                    pairedCredentialCreatedAt = null
                    pairedHubIdentity = null
                    mutableUiState.value = mutableUiState.value.hubRestoreFailed(
                        "Pairing could not be stored and was not activated. Revoke any stale " +
                            "credential on the Mac, then create a new challenge.",
                    )
                }
            }
        }
    }

    fun forgetHub() {
        val previousConfig = hubConfig
        val previousCredentialId = pairedCredentialId
        val wasPaired = mutableUiState.value.hubLinkState == HubLinkState.PAIRED &&
            previousConfig != null &&
            previousCredentialId != null
        ++linkRevision
        val previousLinkJob = linkJob
        previousLinkJob?.cancel()
        operatorAuditJob?.cancel()
        cancelActiveTask()
        hubConfig = null
        pairedCredentialId = null
        pairedCredentialCreatedAt = null
        pairedHubIdentity = null
        mutableUiState.value = mutableUiState.value.hubForgetStarted(nowMillis())
        linkJob = viewModelScope.launch {
            previousLinkJob?.join()
            val localCleared = try {
                withContext(credentialDispatcher) { credentialStore.clear() }
                true
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                false
            }
            val remoteVerified = if (wasPaired) {
                try {
                    pairingGateway.revokeSelf(previousConfig, previousCredentialId)
                    true
                } catch (error: CancellationException) {
                    throw error
                } catch (_: HubPairingException) {
                    false
                } catch (_: Exception) {
                    false
                }
            } else {
                null
            }

            mutableUiState.value = when {
                localCleared && remoteVerified == true -> mutableUiState.value.forgetHub(
                    defaultEndpoint = defaultEndpoint,
                    notice = HubLinkNotice(
                        "Hub revocation verified; local credential removed.",
                        warning = false,
                    ),
                    terminalAtEpochMillis = nowMillis(),
                )
                localCleared && remoteVerified == false -> mutableUiState.value.forgetHub(
                    defaultEndpoint = defaultEndpoint,
                    notice = HubLinkNotice(
                        "Local credential removed; Hub revocation was not verified. Revoke from Mac.",
                        warning = true,
                    ),
                    terminalAtEpochMillis = nowMillis(),
                )
                localCleared -> mutableUiState.value.forgetHub(
                    defaultEndpoint = defaultEndpoint,
                    notice = HubLinkNotice(
                        "Debug Hub link removed from this phone.",
                        warning = false,
                    ),
                    terminalAtEpochMillis = nowMillis(),
                )
                remoteVerified == true -> mutableUiState.value.hubForgetVerificationFailed(
                    defaultEndpoint = defaultEndpoint,
                    message = "Hub revocation was verified, but local credential deletion could not be fully verified. Clear app data before relaunching.",
                    terminalAtEpochMillis = nowMillis(),
                )
                else -> mutableUiState.value.hubForgetVerificationFailed(
                    defaultEndpoint = defaultEndpoint,
                    message = "Current Mac access is disabled, but local credential deletion could not be fully verified. Clear app data before relaunching.",
                    terminalAtEpochMillis = nowMillis(),
                )
            }
        }
    }

    fun rotateHubCredential() {
        if (mutableUiState.value.linkOperationInProgress) return
        val previousConfig = hubConfig
        val previousCredentialId = pairedCredentialId
        val previousCreatedAt = pairedCredentialCreatedAt
        val previousHubIdentity = pairedHubIdentity
        val wasPaired = mutableUiState.value.hubLinkState == HubLinkState.PAIRED &&
            previousConfig != null &&
            previousCredentialId != null &&
            previousCreatedAt != null &&
            previousHubIdentity != null
        if (!wasPaired) {
            mutableUiState.value = mutableUiState.value.hubConfigurationRejected(
                "Token rotation requires a paired Hub link.",
            )
            return
        }
        val rotationConfig = checkNotNull(previousConfig)
        val rotationCredentialId = checkNotNull(previousCredentialId)
        val credentialCreatedAt = checkNotNull(previousCreatedAt)
        val hubIdentity = checkNotNull(previousHubIdentity)

        val revision = ++linkRevision
        val previousLinkJob = linkJob
        previousLinkJob?.cancel()
        operatorAuditJob?.cancel()
        cancelActiveTask()
        mutableUiState.value = mutableUiState.value.hubRotationStarted(nowMillis())
        linkJob = viewModelScope.launch {
            previousLinkJob?.join()
            try {
                val rotated = pairingGateway.rotateSelf(rotationConfig, rotationCredentialId)
                val candidate = StoredHubCredential.create(
                    endpoint = rotationConfig.endpoint,
                    credentialId = rotationCredentialId,
                    deviceId = deviceId,
                    accessToken = rotated.accessToken,
                    createdAt = credentialCreatedAt,
                    hubIdentity = hubIdentity,
                    allowInsecureLoopback = allowInsecureLoopback,
                )
                val persisted = withContext(credentialDispatcher) {
                    credentialStore.save(candidate)
                }
                if (revision != linkRevision) return@launch
                hubConfig = persisted.toHubConfig(allowInsecureLoopback)
                pairedCredentialId = persisted.credentialId
                pairedCredentialCreatedAt = persisted.createdAt
                pairedHubIdentity = persisted.hubIdentity
                deviceId = persisted.deviceId
                mutableUiState.value = mutableUiState.value.hubRotationSucceeded(
                    HubLinkNotice(
                        "Hub token rotated and saved. New Mac requests will reconnect.",
                        warning = false,
                    ),
                )
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                if (revision == linkRevision) {
                    hubConfig = null
                    pairedCredentialId = null
                    pairedCredentialCreatedAt = null
                    pairedHubIdentity = null
                    runCatching {
                        withContext(credentialDispatcher) { credentialStore.clear() }
                    }
                    mutableUiState.value = mutableUiState.value.hubRotationFailed(
                        "Hub token rotation was not verified. Mac access is disabled; pair again and inspect Hub credentials.",
                    )
                }
            }
        }
    }

    fun cancelForegroundPairing() {
        if (mutableUiState.value.hubLinkState != HubLinkState.PAIRING) return
        ++linkRevision
        val enrollmentJob = linkJob
        enrollmentJob?.cancel()
        operatorAuditJob?.cancel()
        hubConfig = null
        pairedCredentialId = null
        pairedCredentialCreatedAt = null
        pairedHubIdentity = null
        mutableUiState.value = mutableUiState.value.hubPairingRejected(
            "Pairing stopped when GOFFY left the foreground. Revoke any newly listed " +
                "credential on the Mac before trying again.",
        )
        linkJob = viewModelScope.launch {
            enrollmentJob?.join()
            try {
                withContext(credentialDispatcher) { credentialStore.clear() }
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.hubRestoreFailed(
                    "Pairing stopped, but local credential cleanup could not be fully verified.",
                )
            }
        }
    }

    fun submitCommand(command: String) {
        refreshLocalModelStatus()
        if (mutableUiState.value.isBusy) {
            mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "Another task is already running; cancel it before submitting a new command",
                nowMillis(),
            )
            return
        }
        val decision = GoffyIntentRouter.route(command, localModelFallback)
        refreshLocalModelStatus()
        if (decision is RoutingDecision.Unsupported) {
            when (val start = startLocalModelObservationIfAvailable(command, decision)) {
                LocalModelObservationStart.Started -> return
                is LocalModelObservationStart.Skipped -> {
                    mutableUiState.value = mutableUiState.value.rejectCommand(
                        command,
                        start.rejectionSummary ?: decision.unsupportedSummary(),
                        nowMillis(),
                    )
                    return
                }
            }
        }

        val plan = (decision as RoutingDecision.Routed).plan
        when (plan.executionTarget) {
            ExecutionTarget.PHONE -> submitPhonePlan(plan)
            ExecutionTarget.MAC -> {
                val config = hubConfig
                if (config == null) {
                    mutableUiState.value = mutableUiState.value.rejectPlan(
                        plan,
                        "Configure a secure GOFFY Hub link before running a Mac task",
                        nowMillis(),
                    )
                    return
                }
                val request = codec.createToolInvocation(deviceId, plan.toolName, plan.arguments)
                executeTask(request.messageId, plan, gateway.invoke(config, request))
            }
            ExecutionTarget.CLOUD -> mutableUiState.value = mutableUiState.value.rejectPlan(
                plan,
                "Cloud execution is not available in this build",
                nowMillis(),
            )
        }
    }

    private fun startLocalModelObservationIfAvailable(
        command: String,
        decision: RoutingDecision.Unsupported,
    ): LocalModelObservationStart {
        val provider = localModelRuntimeProvider ?: return LocalModelObservationStart.Skipped()
        if (!localModelObservationExecutionAvailable) return LocalModelObservationStart.Skipped()
        if (decision.localModelObservation is LocalModelIntentObservation.Rejected) {
            return LocalModelObservationStart.Skipped()
        }
        val status = currentLocalModelStatus()
        mutableUiState.value = mutableUiState.value.copy(localModelStatus = status)
        if (status.state != LocalModelRuntimeState.READY) {
            return LocalModelObservationStart.Skipped(status.unsupportedObservationSummary())
        }
        val taskId = nextTaskId()
        mutableUiState.value = mutableUiState.value.copy(
            executionTarget = ExecutionTarget.PHONE,
            timeline = mutableUiState.value.timeline.startLocalModelObservation(
                taskId = taskId,
                command = command,
                statusSummary = status.summary,
            ),
        )
        val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
            try {
                val observation = provider.observeUnsupportedCommand(decision.normalizedCommand)
                mutableUiState.value = mutableUiState.value.copy(
                    localModelStatus = currentLocalModelStatus(),
                    timeline = mutableUiState.value.timeline.completeLocalModelObservation(
                        taskId = taskId,
                        observation = observation,
                        terminalAtEpochMillis = nowMillis(),
                    ),
                )
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.copy(
                    localModelStatus = currentLocalModelStatus(),
                    timeline = mutableUiState.value.timeline.completeLocalModelObservation(
                        taskId = taskId,
                        observation = LocalModelIntentObservation.Rejected(
                            "Local model observation failed without producing a safe routing hint.",
                        ),
                        terminalAtEpochMillis = nowMillis(),
                    ),
                )
            } finally {
                if (activeJob === coroutineContext[Job]) {
                    activeJob = null
                }
            }
        }
        activeJob = job
        job.start()
        return LocalModelObservationStart.Started
    }

    fun refreshHubOperatorAudit() {
        if (mutableUiState.value.hubOperatorAudit.state == HubOperatorAuditState.LOADING) return
        val config = hubConfig
        if (mutableUiState.value.hubLinkState != HubLinkState.PAIRED || config == null) {
            mutableUiState.value = mutableUiState.value.hubOperatorAuditFailed(
                "Hub audit retrieval requires a paired Hub link.",
            )
            return
        }
        val revision = linkRevision
        operatorAuditJob?.cancel()
        mutableUiState.value = mutableUiState.value.hubOperatorAuditLoading()
        operatorAuditJob = viewModelScope.launch {
            try {
                val snapshot = operatorAuditGateway.listSelfEvents(
                    config,
                    DEFAULT_HUB_OPERATOR_AUDIT_LIMIT,
                )
                if (revision != linkRevision) return@launch
                mutableUiState.value = mutableUiState.value.hubOperatorAuditLoaded(
                    snapshot,
                    nowMillis(),
                )
            } catch (error: CancellationException) {
                throw error
            } catch (error: HubOperatorAuditException) {
                if (revision == linkRevision) {
                    mutableUiState.value = mutableUiState.value.hubOperatorAuditFailed(
                        error.message ?: "Hub audit retrieval failed safely.",
                    )
                }
            } catch (_: Exception) {
                if (revision == linkRevision) {
                    mutableUiState.value = mutableUiState.value.hubOperatorAuditFailed(
                        "Hub audit retrieval failed safely.",
                    )
                }
            } finally {
                if (operatorAuditJob === coroutineContext[Job]) {
                    operatorAuditJob = null
                }
            }
        }
    }

    private fun submitPhonePlan(plan: GoffyExecutionPlan) {
        val taskId = nextTaskId()
        when (plan.permission) {
            PermissionLevel.SAFE -> executeTask(
                taskId,
                plan,
                phoneGateway.invoke(taskId, plan, PhoneToolAuthorization.Safe),
            )
            PermissionLevel.CONFIRM -> requestPhoneApproval(taskId, plan)
            PermissionLevel.SENSITIVE,
            PermissionLevel.BLOCKED,
            -> mutableUiState.value = mutableUiState.value.rejectPlan(
                plan,
                "This phone action is blocked in the current security policy",
                nowMillis(),
            )
        }
    }

    private fun requestPhoneApproval(taskId: UUID, plan: GoffyExecutionPlan) {
        val description = plan.approvalDescription()
        if (description == null) {
            mutableUiState.value = mutableUiState.value.rejectPlan(
                plan,
                "The confirmation request did not match a typed phone tool",
                nowMillis(),
            )
            return
        }
        val expiresAt = nowMillis() + approvalTtlMillis
        val approval = PendingApproval(
            taskId = taskId,
            toolName = plan.toolName,
            description = description,
            expiresAtEpochMillis = expiresAt,
            durationSeconds = (approvalTtlMillis + 999L) / 1_000L,
        )
        mutableUiState.value = mutableUiState.value
            .startTask(taskId, plan)
            .awaitApproval(approval, nowMillis())
        pendingExecution = PendingPhoneExecution(taskId, plan, expiresAt)
        approvalExpiryJob = viewModelScope.launch {
            delay(approvalTtlMillis)
            expirePendingApproval(taskId)
        }
    }

    private fun GoffyExecutionPlan.approvalDescription(): String? = when (val value = arguments) {
        is PhoneNoteCreateArguments ->
            "Approve creating this private note: ${value.text.take(APPROVAL_PREVIEW_LENGTH)}"
        is PhoneTimerCreateArguments ->
            "Approve requesting a ${value.durationSeconds.displayDuration()} system Clock timer. " +
                "GOFFY will request no second Clock confirmation screen."
        is PhoneFlashlightSetArguments ->
            "Approve turning ${if (value.enabled) "on" else "off"} the back-camera flashlight. " +
                "GOFFY will not open the camera or capture images."
        else -> null
    }

    private fun refreshLocalModelStatus() {
        mutableUiState.value = mutableUiState.value.copy(localModelStatus = currentLocalModelStatus())
    }

    private fun currentLocalModelStatus(): LocalModelRuntimeStatus {
        val status = localModelStatusProvider()
        if (
            localModelRuntimeProvider != null &&
            !localModelObservationExecutionAvailable &&
            status.state == LocalModelRuntimeState.READY
        ) {
            return status.copy(
                state = LocalModelRuntimeState.UNAVAILABLE,
                summary = "Local model setting is enabled; unsupported-command execution is not wired yet.",
            )
        }
        return status
    }

    private fun RoutingDecision.Unsupported.unsupportedSummary(): String =
        when (val observation = localModelObservation) {
            is LocalModelIntentObservation.Candidate ->
                "Local model suggested ${observation.candidate.intentLabel}, but GOFFY needs " +
                    "a deterministic route before execution"
            is LocalModelIntentObservation.Disabled ->
                "No safe deterministic route is available for this command yet. ${observation.reason}"
            is LocalModelIntentObservation.Rejected ->
                "No safe deterministic route is available for this command yet. ${observation.reason}"
            null -> "No safe deterministic route is available for this command yet"
        }

    private fun LocalModelRuntimeStatus.unsupportedObservationSummary(): String =
        "No safe deterministic route is available for this command yet. " +
            "Local model observation is unavailable: $summary"

    private fun Int.displayDuration(): String = when {
        this % 3_600 == 0 -> "${this / 3_600} ${if (this == 3_600) "hour" else "hours"}"
        this % 60 == 0 -> "${this / 60} ${if (this == 60) "minute" else "minutes"}"
        else -> "$this ${if (this == 1) "second" else "seconds"}"
    }

    fun approvePendingTask(taskId: UUID): Boolean {
        val pending = pendingExecution ?: return false
        if (pending.taskId != taskId) return false
        if (nowMillis() >= pending.expiresAtEpochMillis) {
            expirePendingApproval(taskId)
            return false
        }
        pendingExecution = null
        approvalExpiryJob?.cancel()
        approvalExpiryJob = null
        mutableUiState.value = mutableUiState.value.grantApproval(taskId, nowMillis())
        collectTask(
            taskId,
            phoneGateway.invoke(
                taskId,
                pending.plan,
                PhoneToolAuthorization.Approved(
                    taskId,
                    pending.plan.toolName,
                    pending.plan.arguments,
                    pending.expiresAtEpochMillis,
                ),
            ),
        )
        return true
    }

    fun denyPendingTask(taskId: UUID): Boolean {
        val pending = pendingExecution ?: return false
        if (pending.taskId != taskId) return false
        pendingExecution = null
        approvalExpiryJob?.cancel()
        approvalExpiryJob = null
        mutableUiState.value = mutableUiState.value.denyApproval(
            taskId,
            "Approval denied; no phone tool was invoked",
            nowMillis(),
        )
        return true
    }

    private fun expirePendingApproval(taskId: UUID) {
        val pending = pendingExecution ?: return
        if (pending.taskId != taskId) return
        pendingExecution = null
        approvalExpiryJob = null
        mutableUiState.value = mutableUiState.value.expireApproval(taskId, nowMillis())
    }

    private fun executeTask(
        taskId: UUID,
        plan: GoffyExecutionPlan,
        events: Flow<ExecutionEvent>,
    ) {
        mutableUiState.value = mutableUiState.value.startTask(taskId, plan)
        collectTask(taskId, events)
    }

    private fun collectTask(
        taskId: UUID,
        events: Flow<ExecutionEvent>,
    ) {
        val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
            try {
                events.collect { event ->
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(
                        taskId,
                        event,
                        nowMillis(),
                    )
                }
                if (mutableUiState.value.timeline.activeTaskId == taskId) {
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(
                        taskId,
                        ExecutionEvent.Error(
                            code = "execution_stopped",
                            message = "Execution stopped before verification",
                            retryable = false,
                        ),
                        nowMillis(),
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.applyTaskEvent(
                    taskId,
                    ExecutionEvent.Error(
                        code = "client_failure",
                        message = "The Android execution client stopped before verification",
                        retryable = false,
                    ),
                    nowMillis(),
                )
            } finally {
                if (activeJob === coroutineContext[Job]) {
                    activeJob = null
                }
            }
        }
        activeJob = job
        job.start()
    }

    fun cancelActiveTask() {
        val pending = pendingExecution
        if (pending != null) {
            pendingExecution = null
            approvalExpiryJob?.cancel()
            approvalExpiryJob = null
            mutableUiState.value = mutableUiState.value.denyApproval(
                pending.taskId,
                "Approval cancelled; no phone tool was invoked",
                nowMillis(),
            )
            return
        }
        activeJob?.cancel()
        activeJob = null
        mutableUiState.value = mutableUiState.value.cancelActiveTask(nowMillis())
    }

    override fun onCleared() {
        linkJob?.cancel()
        operatorAuditJob?.cancel()
        localModelSettingsJob?.cancel()
        approvalExpiryJob?.cancel()
        auditStore.close()
        phoneGateway.close()
        pairingGateway.close()
        operatorAuditGateway.close()
        gateway.close()
        super.onCleared()
    }

    class Factory(context: Context) : ViewModelProvider.Factory {
        private val applicationContext = context.applicationContext

        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(GoffyViewModel::class.java)) {
                "Unsupported ViewModel class"
            }
            @Suppress("UNCHECKED_CAST")
            return GoffyViewModel(applicationContext) as T
        }
    }

    private companion object {
        const val DEBUG_HUB_ENDPOINT = "ws://127.0.0.1:8787/ws/v1"
        const val RELEASE_HUB_ENDPOINT_HINT = "wss://your-mac.example:8787/ws/v1"
        const val DEFAULT_APPROVAL_TTL_MILLIS = 60_000L
        const val APPROVAL_PREVIEW_LENGTH = 160
    }

    private data class PendingPhoneExecution(
        val taskId: UUID,
        val plan: GoffyExecutionPlan,
        val expiresAtEpochMillis: Long,
    )

    private object NoOpTerminalAuditStore : TerminalAuditStore {
        override suspend fun load() = ClosedTerminalAuditLoadResult(emptyList(), 0)

        override suspend fun upsert(record: ClosedTerminalAuditRecord) = record

        override fun close() = Unit
    }

    private object NoOpLocalModelRuntimeSettingsStore : LocalModelRuntimeSettingsStore {
        override fun load(): LocalModelRuntimeSettingsLoadResult =
            LocalModelRuntimeSettingsLoadResult.Loaded(LocalModelRuntimeSettings())

        override fun save(settings: LocalModelRuntimeSettings): LocalModelRuntimeSettingsSaveResult =
            LocalModelRuntimeSettingsSaveResult.Saved(settings)
    }
}

private data class AndroidGoffyDependencies(
    val context: Context,
    val localModelSettingsStore: LocalModelRuntimeSettingsStore,
    val localModelSettingsSource: MutableLocalModelRuntimeSettingsSource,
    val localModelRuntimeProvider: LocalModelRuntimeProvider?,
    val localModelControlsAvailable: Boolean,
    val localModelObservationExecutionAvailable: Boolean,
)

private sealed interface LocalModelObservationStart {
    object Started : LocalModelObservationStart

    data class Skipped(val rejectionSummary: String? = null) : LocalModelObservationStart
}

private fun createAndroidGoffyDependencies(context: Context): AndroidGoffyDependencies {
    val applicationContext = context.applicationContext
    val localModelSettingsSource = MutableLocalModelRuntimeSettingsSource(
        LocalModelRuntimeSettings(
            enabledByUser = BuildConfig.GOFFY_LOCAL_MODEL_USER_ENABLED_DEFAULT,
        ),
    )
    val localModelRuntimeProvider = LocalModelRuntimeProviderLoader.create(
        applicationContext,
        localModelSettingsSource,
    )
    return AndroidGoffyDependencies(
        context = applicationContext,
        localModelSettingsStore = AndroidLocalModelRuntimeSettingsStore(applicationContext),
        localModelSettingsSource = localModelSettingsSource,
        localModelRuntimeProvider = localModelRuntimeProvider,
        localModelControlsAvailable =
            BuildConfig.GOFFY_LOCAL_MODEL_DEVELOPER_RUNTIME_ALLOWED && localModelRuntimeProvider != null,
        localModelObservationExecutionAvailable = localModelRuntimeProvider != null,
    )
}
