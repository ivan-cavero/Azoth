# Javelin message GUID registry (build 8654f01d...dc8e)

> Extracted 2026-10-08 from the executable's static type-descriptor
> region: each `XxxMsg` name is stored immediately before its AZ type
> GUID. This is the **canonical identifier** for every Javelin message
> type. The `type` numbers on the wire (e.g. `0x635`) are indices into
> the per-build type table, not these GUIDs; use the GUID to match a
> wire type across builds, and use `typeindex.json` for the index.
>
> Method: scan of `NewWorld.exe` for `[A-Za-z0-9]+Msg` + NULs + a GUID
> (the same static region the typed dispatcher `FUN_146b6f190` reads
> through its accessors and compares with `FUN_146158ba0`). 156 found.

Total: **156** types.

## Movement family (the movement-blocker lead)

The client's movement is RMI-driven. These are the movement types:

- `AbortMovementMsg` -- `adaa28e6-b831-4505-8f05-fe32e000bd5d`
- `AckMovementMsg` -- `5ad005ae-375c-4f2d-a00e-3ff9f6f01069`
- `CancelMovementMsg` -- `a9da71b4-4dcf-46e6-afa2-dbbe9e5ced0e`
- `CheckMovementStatusMsg` -- `44ba8334-c3aa-476e-855c-27364bf8a964`
- `CommitMovementMsg` -- `78ec38b5-d408-4f06-8aaf-60e7fda45cee`
- `CrashMoveActorToHubMsg` -- `6f298c98-a99e-4210-ad2a-e48d3cd775ee`
- `MoveActorMsg` -- `5570cfb7-0c5c-475e-bb19-d8fbc3fd8d32`
- `MoveActorToHubMsg` -- `0a8f6818-915c-4700-9c33-463862bbe5f0`
- `MoveAnActorMsg` -- `4d1e559d-3e99-4171-9daf-58810e245447`
- `MovementTimeoutMsg` -- `4604a3cc-2cac-4a93-a0e2-d330041777e6`
- `OnMoveCoordinatorChangedMsg` -- `020037e0-103c-4c2d-ae9a-7c9b31d3ccf2`
- `ProcessDeferredMovementRequestsMsg` -- `4c220b64-c728-4d31-9c1e-6244e8089215`
- `ReceivePlayerPositionClientMsg` -- `39ca8bca-2ee8-4104-b0e9-7c2a51b52fb4`
- `StartMovementCommunicationMsg` -- `767fc9bf-1c8d-417f-ad19-c51e363d4df0`

## Other notable families

- Registration: `RegistrationRequestMsg`, `RegistrationRequestV2Msg`, `RegistrationRequestV3Msg`, `RegistrationResponseMsg`
- Guild: 20 types
- Hub / lifecycle: 14 types
- Ping / time: `MovementTimeoutMsg`, `OnGameModeLongTimeoutMsg`, `PingMsg`, `PingRequestMsg`, `PingResponseMsg`, `SendClockSyncMsg`, `TestStepTimeoutMsg`, `TimeSynchMsg`, `TimeoutMigrationsAtCommitMsg`, `TimeoutMigrationsMsg`
- Actor spawn/migration: `MoveActorMsg`, `MoveActorToHubMsg`, `OnActorMigratedMsg`, `ReceiveActorMsg`, `ReceiveAllHubNamesMsg`, `ReceiveConfigOverridesKeyValuePairsMsg`, `ReceiveConfigOverridesMsg`, `ReceiveHubInfoForActorsMsg`, `ReceiveManagerConfigurationMsg`, `ReceivePlayerPositionClientMsg`, `RespawnPrefabClientDebugMsg`, `SpawnActorsMsg`, `SpawnRestoredMonikerActorMsg`, `SpawnRestoredSpatialActorMsg`, `TargetInitMsg`

## Full registry

| Type | GUID |
| --- | --- |
| `AbortMovementMsg` | `adaa28e6-b831-4505-8f05-fe32e000bd5d` |
| `AckHubLifecycleStepUpdateMsg` | `cc4399fa-86d8-4e83-8889-79fb720f00fc` |
| `AckMovementMsg` | `5ad005ae-375c-4f2d-a00e-3ff9f6f01069` |
| `ActorQueryMsg` | `3b75f658-048e-4e13-b96b-47973f4f1ae6` |
| `AddEndpointsMsg` | `285d5e35-0103-4b07-8a8e-b60793f12ee4` |
| `AddEntryMsg` | `04c84157-b7aa-4912-8d81-fae46f93ec92` |
| `AdvanceTestMsg` | `e00f4b58-7475-4beb-921a-f50594717801` |
| `CancelMovementMsg` | `a9da71b4-4dcf-46e6-afa2-dbbe9e5ced0e` |
| `CheckMovementStatusMsg` | `44ba8334-c3aa-476e-855c-27364bf8a964` |
| `ClearRemoteRegistryMsg` | `63de8b4f-d87d-424b-8a8b-38bd45b7cff5` |
| `ClientAddEntryMsg` | `e3578b38-69ad-4c13-a7dd-3fff752d98aa` |
| `ClientAliveMsg` | `1df83613-5012-4a79-8c63-e35962b01ee4` |
| `ClientConnectionMsg` | `c4f1e7b5-d502-49f4-ac71-27928c9d25c5` |
| `ClientDisconnectionMsg` | `cabd72ff-cca0-4c8a-804e-c585b386dcfe` |
| `ClientRemoveEntryMsg` | `3c70b3a4-f1c9-4206-9c3b-2e8d132c95c4` |
| `ClientTestFunctionMsg` | `ca011ff3-648d-4960-9e77-20f5b924c772` |
| `CommitMovementMsg` | `78ec38b5-d408-4f06-8aaf-60e7fda45cee` |
| `CompleteDelayedMigrationsMsg` | `15203a91-c8b6-43ee-bdf6-571a30c8b8b0` |
| `ConfigurablePayloadMsg` | `a0dcfefc-2684-48b6-a7ef-83bedff00e45` |
| `ConfigureTestActorsMsg` | `0bb0c8ef-4a2a-43e1-a202-b1fa65cb0cae` |
| `ConfirmRecordRequestMsg` | `a0511bd9-3e54-4e1d-a3af-ff80c77e6a5a` |
| `ConfirmRecordResponseMsg` | `d182278b-4909-4763-a56f-ba7319d8521a` |
| `ContinueLifecycleStartupMsg` | `9719faec-9a26-4a60-aef5-6c018a9819ae` |
| `CrashMoveActorToHubMsg` | `6f298c98-a99e-4210-ad2a-e48d3cd775ee` |
| `CrashReceiveActorMsg` | `61fdb168-4ac2-4e31-8cd1-c4b9f40f7d16` |
| `DebugStartActorQuerySeqMsg` | `180f5983-16c0-4389-bf5d-fe820a15a439` |
| `DelayMigrationsMsg` | `890a8aa5-67df-4ed6-a872-589c60a80190` |
| `EndTestMsg` | `4208c33b-6441-4900-9c8d-168ffdcd3986` |
| `ExecuteDebugCommandMsg` | `178ad7c6-9818-4edf-9694-87bd5b641d43` |
| `ExitPeeringMsg` | `538cf087-049b-41d1-9df1-a7b23b55e8c6` |
| `FilterChatResponseMsg` | `951d5056-809a-4019-b6d5-30f89d9c96a8` |
| `FilterTextResponseMsg` | `e4b8c624-9165-4a9a-9dfd-61b670b32ee3` |
| `FinalizeReconnectCrossWorldMsg` | `686c6f88-5cd5-47e0-a3ee-80571c27a44e` |
| `ForwardedMessageMsg` | `b55c7649-434c-40b1-aa4f-54085f2bd931` |
| `FragmentUpdateMsg` | `951ef3ed-c9a0-4e3d-a6fd-7fe0673d28d2` |
| `GoodbyeMsg` | `92076eda-c7f2-4cf9-a3cd-10e3002e7109` |
| `HubConnectionChangedMsg` | `b73ccf2d-cb1d-4ad6-9296-a7b4d5a0d992` |
| `InitMsg` | `177e0cff-f70c-4d87-9551-b3010ea29389` |
| `InitiateReconnectCrossWorldMsg` | `f9f85561-f9a1-43c9-b3cd-e714cbc80124` |
| `IsUsingBadWordsMsg` | `47ebd2d4-4b67-43d9-9535-2ddb7c223501` |
| `IsUsingBadWordsResponseMsg` | `0e289a49-92a6-42d9-8d89-093ac00837f7` |
| `KickClientFromRepMsg` | `8a5e870c-878b-4190-a41d-9503ebf2276e` |
| `KickClientMsg` | `4a0a26f6-f24e-4239-a771-7ba1f135c6fd` |
| `LoadConfigurationMsg` | `75538b51-8e0f-432f-8077-61b0a60854ac` |
| `MoveActorMsg` | `5570cfb7-0c5c-475e-bb19-d8fbc3fd8d32` |
| `MoveActorToHubMsg` | `0a8f6818-915c-4700-9c33-463862bbe5f0` |
| `MoveAnActorMsg` | `4d1e559d-3e99-4171-9daf-58810e245447` |
| `MovementTimeoutMsg` | `4604a3cc-2cac-4a93-a0e2-d330041777e6` |
| `NoFragmentsPresentMsg` | `9d63d9bd-09da-45c4-b209-4dd5a924a295` |
| `NotifyClientMessageMetadataMsg` | `ec647fbe-e799-4b67-85ec-a35ef4f6438f` |
| `NotifyHubCrashMsg` | `e0804a74-d828-4d11-acf6-9554a0c30b75` |
| `NotifyPersistenceLoadedMsg` | `451436ac-6702-4482-b53b-63274d877bc5` |
| `OnActorMigratedMsg` | `df0b0a76-cc04-4b02-9f8c-4b8607df695b` |
| `OnCrossWorldReconnectStatusUpdateMsg` | `3436d1ee-39ce-4bbd-a96d-0c5efe1918e9` |
| `OnDataRequestFailedMsg` | `ee7774e7-b701-4a57-850b-fc6d5918e429` |
| `OnDebugPersistentValuesMsg` | `ce7c7403-5786-4723-9195-9b543a188ce3` |
| `OnDepositGuildTreasuryFundsFailedMsg` | `7bed58ca-9e5e-4915-bc95-31615b24dadd` |
| `OnDepositGuildTreasuryFundsMsg` | `caa452ad-8701-40d9-8f00-0795ad0b32a7` |
| `OnEditGuildCrestFailedMsg` | `839314ba-2436-4d3e-b428-4ecccd94a407` |
| `OnEditGuildCrestSucceededMsg` | `1dbcdb71-5db8-4d94-8c33-3484e6872f77` |
| `OnEditGuildMOTDFailedMsg` | `52ca232d-e0cf-4693-93c5-15af6d5faade` |
| `OnEnterDungeonRequestIgnoredMsg` | `d2a3e306-d56d-421d-af7e-e7bdc0b9ed35` |
| `OnGameModeLongTimeoutMsg` | `4627393e-3ae6-4f99-b990-5de96d70d8ad` |
| `OnGetGuildTreasuryFailedMsg` | `53d04e83-a9f2-4cf2-9dd2-71a9e323aa12` |
| `OnGetGuildTreasuryWithdrawalLimitFailedMsg` | `eeb43ad9-a9cc-44b7-84fb-ae30a66867fc` |
| `OnGetInvitesFailedMsg` | `8da92ca0-b71b-4a12-bd63-b9317de61a22` |
| `OnGetUnorderedGuildsMsg` | `5cbfe0ed-30ed-4f43-8c72-8726d54963c1` |
| `OnGuildInviteRespondedMsg` | `879f3db0-fd6c-441c-86c5-21232c2b1bee` |
| `OnGuildNameAvailableMsg` | `818b663b-da66-4d35-84b0-d8fccf92d350` |
| `OnGuildRequestErrorMsg` | `8004f4db-e121-47e2-a711-5d768e629505` |
| `OnHubCrashMsg` | `3647beac-ec75-4301-80df-f7ca34d96bdb` |
| `OnInitCompletedMessageMsg` | `422e5af5-88f4-4fc0-9faf-5f8e29959bff` |
| `OnInviteCreatedFailedMsg` | `68125d17-75cd-4266-87a0-072865663c26` |
| `OnLeftQueueForGameModeMsg` | `f8b391ff-9d75-4bd3-8bc1-3cbe1b0850fa` |
| `OnListenerChangedMsg` | `0ee4e646-d75e-4034-b85c-a9897ffc3e19` |
| `OnListenerSubscribedMsg` | `0e72c80f-31c3-4e8f-9b20-4762709f3d3e` |
| `OnMatchmakingForGameModeFailedMsg` | `bdd6d113-f488-48ff-964a-b952b2b48b60` |
| `OnMoveCoordinatorChangedMsg` | `020037e0-103c-4c2d-ae9a-7c9b31d3ccf2` |
| `OnNewHubInfoMsg` | `fd419a47-69a5-4e74-b542-3c105dbb1fec` |
| `OnPeerChangedMsg` | `e02facec-37be-441d-91d3-4a371147d689` |
| `OnQueueForGameModeFailedMsg` | `188644f3-f557-4778-8e1a-f04f4b037c60` |
| `OnRemoveAllGuildInvitesFailedMsg` | `71ca9ad3-a4e3-4b0a-a3a0-235634d27076` |
| `OnRemoveGuildMemberFailedMsg` | `e8c468a7-be17-4f22-b82b-bb62bcbdecc2` |
| `OnRemovePastGuildMemberFailedMsg` | `0c03515b-4554-40c2-b569-35b75836ffc8` |
| `OnRespondToGuildInviteFailedMsg` | `6ed4d89b-df71-4e0c-b144-681c18dcffd7` |
| `OnSentGuildInviteRejectedMsg` | `42d451ff-bb8a-41ae-b986-ad71e1bea427` |
| `OnSetGuildMemberRankFailedMsg` | `0d0ce903-50b0-4a54-a09a-c6219f456ad2` |
| `OnSetGuildMemberRankFailedReasonMsg` | `34fbdc96-628c-4068-af51-a495865e17d6` |
| `OnSetGuildTreasuryWithdrawalLimitFailedMsg` | `402eb227-1b30-439f-b136-b37286de6fd3` |
| `OnSetSiegeWindowFailedMsg` | `cff9287b-bc6a-4e4d-95e6-1f2690cae5c2` |
| `OnSpatialRestoreFinishedMsg` | `5f36c8af-2dca-4ba5-b6f7-8225f77d2fd2` |
| `OnStateChangedMsg` | `678da812-d9d1-45b5-bfb7-07a631f394de` |
| `OnSubRoutingChangedMsg` | `54873248-1da2-4a4b-bf99-c6b70774764c` |
| `OnTargetSpawnedMsg` | `558c24ec-6697-420b-83bd-acc4d1a42029` |
| `OnWithdrawGuildTreasuryFundsFailedMsg` | `e3e85ee0-8196-4c02-8cdd-f7ac61b10f31` |
| `PeerPresenceAckMsg` | `42de4ff0-f4f6-4660-82fa-525cf7795666` |
| `PingMsg` | `85c7e01e-55de-4a6e-afc5-80fa9a8ad260` |
| `PingRequestMsg` | `ad4c28bd-4208-4b47-9679-9a46dd9e5287` |
| `PingResponseMsg` | `259734dd-9277-4e08-b11f-1ab9e71de1be` |
| `PokeMsg` | `1f141400-3979-4069-acbb-ce11f549dc64` |
| `ProcessDeferredMovementRequestsMsg` | `4c220b64-c728-4d31-9c1e-6244e8089215` |
| `ReceiveActorMsg` | `764599e8-3d44-4eb3-bf44-77097cb414e3` |
| `ReceiveAllHubNamesMsg` | `4cf9d4ae-3be1-4e9e-a8f1-a313ab114d00` |
| `ReceiveConfigOverridesKeyValuePairsMsg` | `b40ae287-a16f-48c6-b43f-246cd34ce105` |
| `ReceiveConfigOverridesMsg` | `b8ce47d4-4ce9-4803-8db4-beadba4629ec` |
| `ReceiveHubInfoForActorsMsg` | `64de5c88-0010-4f0b-b554-db02a2a968e8` |
| `ReceiveManagerConfigurationMsg` | `655f8c9d-4ba8-43c9-9ad5-b97f55d26315` |
| `ReceivePlayerPositionClientMsg` | `39ca8bca-2ee8-4104-b0e9-7c2a51b52fb4` |
| `RegisterFragmentAccessMsg` | `96a58e69-7bd5-45c5-86e4-daf9f5eb1e86` |
| `RegistrationRequestMsg` | `8673a3cc-2848-4c87-aa72-cc860589d1b5` |
| `RegistrationRequestV2Msg` | `da4e5889-a65c-4480-8642-0278160125a7` |
| `RegistrationRequestV3Msg` | `0b826b33-89f5-49e0-b8cb-fe4433427778` |
| `RegistrationResponseMsg` | `104145a7-ff95-44f1-9468-21fb41c8ac2b` |
| `RemoveEndpointsMsg` | `6fbc64fe-4cc1-4940-982c-88eb8d3df9d6` |
| `RemoveEntryMsg` | `3988c9eb-8ba6-4c68-ad63-c75475bde6e2` |
| `RequestAllHubNamesMsg` | `877cd24e-3256-4364-8ce4-fad4b9786619` |
| `RequestChangeSpectatorModeStateMsg` | `49ede1c5-389c-4ccb-8287-af7cc7672298` |
| `RequestCycleFocusedPlayerMsg` | `b4cca937-3466-48d0-8c8d-677be9afdddb` |
| `RequestEnterSpectatorModeMsg` | `cd45e2bd-0ba9-48e9-b99f-771de6cd1478` |
| `RequestExitSpectatorModeMsg` | `8ccb5ccd-cf87-4212-8a2c-4dd0e1463afe` |
| `RequestHubInfoForActorsMsg` | `21be4bfa-5bc7-423f-99dc-960fc0fd95ab` |
| `RequestRecordsMsg` | `87586f4e-7f71-4b87-9498-87471ec495cb` |
| `RequestServerAuthPrefabIdMsg` | `f04aa7e8-94e3-41e1-b53a-5824b858b5fa` |
| `RequestServerAuthPrefabIdResponseMsg` | `73c38cc7-d360-4b4d-8ba9-63ce3aa39805` |
| `RequestShutdownTargetMsg` | `977850bd-17ca-4625-a234-76a796d4035a` |
| `RequestSpawnTargetMsg` | `f75c3dcc-bba2-4263-a8f3-80800f1b2efe` |
| `RequestStateMsg` | `39465258-419e-4e0d-b549-63549573dec6` |
| `ResetRecordMsg` | `eead05bb-5fe1-4c67-b053-93ce4a3b22aa` |
| `RespawnPrefabClientDebugMsg` | `287283b0-b7bd-421a-9e59-ecf82b0e1401` |
| `ResponseMsg` | `48d4f289-66fc-4eed-9097-d2d8205dbacd` |
| `RoutingUnsubscribeMsg` | `a6d36734-45b4-4d99-94e8-46ff2819f576` |
| `SendClockSyncMsg` | `efd5616b-2cca-4f25-891c-4d4d0613663c` |
| `SendConfigOverridesMsg` | `d677b2ad-832e-4d43-a1cd-37b0f5183ba4` |
| `SetTargetsMsg` | `1e93f466-cd84-4502-ba28-4632f80dd0fa` |
| `SpawnActorsMsg` | `d1b5b725-b1b5-4a87-9582-ac4509fb9cc4` |
| `SpawnRestoredMonikerActorMsg` | `5ba02fa9-76cf-49be-9cd0-b0ce9f789c83` |
| `SpawnRestoredSpatialActorMsg` | `26cf40ac-aabb-4db5-98e9-fa1c47203fbc` |
| `StartMovementCommunicationMsg` | `767fc9bf-1c8d-417f-ad19-c51e363d4df0` |
| `StartObservingFragmentMsg` | `5f4ce846-ecbc-415b-aae0-85f7e83cde2c` |
| `StartUpdatingMsg` | `fee0688d-06c8-4d66-813d-044d0bd1b70d` |
| `StopObservingFragmentMsg` | `a9ed156f-21d9-491e-83ea-330586a5095a` |
| `StopUpdatingMsg` | `e31b6912-856d-4052-bedf-c23fdbf71774` |
| `TargetInitMsg` | `844b0b91-6f61-4e0a-9b84-b82cd8d35ebe` |
| `TestStepTimeoutMsg` | `66958583-bae9-4540-9d4b-be4604bebe22` |
| `TimeSynchMsg` | `038cd847-0653-4243-9a26-936e3bd7f312` |
| `TimeoutMigrationsAtCommitMsg` | `66185cbc-da8c-47e3-a6d9-20d627d80c5a` |
| `TimeoutMigrationsMsg` | `97b5cc71-075e-4f76-a30c-fc670edad0ab` |
| `ToHubDebugMsg` | `f60358c7-361a-465f-a2f9-e04e27e1e50a` |
| `UnregisterFragmentAccessMsg` | `2b7640e0-4204-4e52-998a-c2db02e0a480` |
| `UnregisterProxyMsg` | `b5733a42-3cc9-442e-b6c7-d83af26dbbb4` |
| `UpdateHubLifecycleStepMsg` | `99e5a445-bbf8-4093-8a8f-cd3577001082` |
| `UpdateMsg` | `1619d3b8-8b45-46aa-b95e-a414dfebc931` |
| `UpdateRecordsMsg` | `8f4bb6ba-3f76-48c7-8bd7-d777bdc61e0b` |
| `UpgradeVersionMsg` | `254f3d8e-5899-4206-88c7-fee4a7362192` |
| `VerifyPeersAckedStepUpdateMsg` | `0af84261-9199-418b-87a7-fcfa16bd5854` |
| `WarnClientMsg` | `c5fc310d-26e9-4e9e-a083-3695c0a86b01` |
