/* Azoth steam_api64 stub v2 (minimal, private launch only).
 *
 * Why minimal: NewWorld.exe 1.400 statically imports only 8 symbols from
 * steam_api64.dll and resolves 4 interfaces via SteamInternal_ContextInit:
 *   SteamUser023 / SteamFriends017 / SteamUtils010 / STEAMAPPS_INTERFACE_VERSION008
 * The old v1 stub exported 1065 symbols with one shared dummy vtable whose
 * every slot returned (void*)1. Any method returning a pointer then caused
 * a 0x1 dereference -> random crashes on startup. v2 fixes that:
 *   - 22 flat exports (the 8 imports + the accessors the game may GetProcAddress)
 *   - 4 separate vtables with type-correct safe defaults:
 *       pointers -> NULL or "" (never 0x1), ints/handles -> 0, bools -> plausible
 *   - minimal Steam callback dispatch (101/163/168) so the Omni login proceeds
 *   - optional file log (AZOTH_STUB_LOG=1) to %TEMP%\azoth_stub.log showing
 *     interface versions, tickets, callbacks and vtable probes.
 *
 * Provenance: every non-obvious answer here was earned against the running
 * client (see tools/azoth_dbg.py), not copied from the SDK.
 *
 * x64 note: Windows x64 has a single calling convention (caller cleans the
 * stack), so a callee that ignores its args and returns in RAX is safe even
 * if the declared prototype is simplified to (void* self, ...). All thunks
 * below use minimal prototypes and only touch RAX (+ out-params we own).
 */

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include "config.h"

#define API __declspec(dllexport)

/* ---------------------------------------------------------------- log --- */

static int g_log_on = -1;
static char g_log_path[MAX_PATH];

static void log_line(const char *msg, const char *extra) {
    if (g_log_on == -1) {
        g_log_on = (GetEnvironmentVariableA("AZOTH_STUB_LOG", NULL, 0) > 0) ? 1 : 0;
        if (g_log_on) {
            char tmp[MAX_PATH];
            DWORD n = GetEnvironmentVariableA("TEMP", tmp, sizeof(tmp));
            if (!n || n >= sizeof(tmp)) strcpy_s(tmp, sizeof(tmp), ".");
            _snprintf_s(g_log_path, sizeof(g_log_path), _TRUNCATE, "%s\\azoth_stub.log", tmp);
        }
    }
    if (!g_log_on) return;
    FILE *f = NULL;
    fopen_s(&f, g_log_path, "a");
    if (!f) return;
    DWORD tick = GetTickCount();
    if (extra && *extra) fprintf(f, "[%lu] %s %s\n", (unsigned long)tick, msg, extra);
    else fprintf(f, "[%lu] %s\n", (unsigned long)tick, msg);
    fclose(f);
}

/* ------------------------------------------------------- safe statics --- */

static const char k_persona[] = AZOTH_PERSONA;
static const char k_lang[] = AZOTH_LANG;
static const char k_country[] = AZOTH_COUNTRY;
static const char k_empty[] = "";

/* Generic thunks (x64-safe: ignore args, return in RAX). */
static uint64_t __fastcall t_u64_1(void *s) { (void)s; return 1; }
static void __fastcall t_void(void *s) { (void)s; }
static const char *__fastcall t_str_empty(void *s) { (void)s; return k_empty; }

/* Per-interface defaults: safe zero + one-line trace so the stub log shows
 * which interface the game pokes beyond the implemented slots. */
static int g_seen_u = 0, g_seen_f = 0, g_seen_w = 0, g_seen_a = 0;
static uint64_t __fastcall u_def(void *s) {
    (void)s;
    if (!g_seen_u) { g_seen_u = 1; log_line("User:default-slot", ""); }
    return 0;
}
static uint64_t __fastcall f_def(void *s) {
    (void)s;
    if (!g_seen_f) { g_seen_f = 1; log_line("Friends:default-slot", ""); }
    return 0;
}
static uint64_t __fastcall w_def(void *s) {
    (void)s;
    if (!g_seen_w) { g_seen_w = 1; log_line("Utils:default-slot", ""); }
    return 0;
}
static uint64_t __fastcall a_def(void *s) {
    (void)s;
    if (!g_seen_a) { g_seen_a = 1; log_line("Apps:default-slot", ""); }
    return 0;
}

/* One-line trace per process for hot thunks (keeps %TEMP%\azoth_stub.log small
 * while showing the exact last stub call before any early exit). */
#define TRACE_ONCE(msg) do { static int _once = 0; if (!_once) { _once = 1; log_line(msg, ""); } } while (0)

/* --- ISteamUser023 (33 methods, SDK order) --- */
static int32_t __fastcall u_GetHSteamUser(void *s) { (void)s; TRACE_ONCE("User:GetHSteamUser"); return 1; }
static uint8_t __fastcall u_BLoggedOn(void *s) { (void)s; TRACE_ONCE("User:BLoggedOn"); return 1; }
/* Client 1.400 fact (proven with tools/azoth_dbg.py + Game.log correlation):
 * the SteamAuth path calls User slot 2 and DEREFERENCES the result as a
 * CSteamID* (`mov rcx,[rax]` at NewWorld+0x5a7f7ae). Returning the integer ID
 * faults (0xc0000005, Rax==ID). So slot 2 returns the ADDRESS of a static ID:
 * the crashing path reads *ptr == AZOTH_STEAMID into its field and proceeds.
 * Only one caller exists in this build (see stub log), so nothing else is
 * affected. Revisit if a future client expects the integer. */
static uint64_t k_steamid_slot = AZOTH_STEAMID;
static uint64_t __fastcall u_GetSteamID(void *s) {
    (void)s;
    TRACE_ONCE("User:GetSteamID");
    return (uint64_t)(uintptr_t)&k_steamid_slot;
}
static void *__fastcall u_Ticket(void *s, void *buf, int cbMax, uint32_t *pcb) {
    (void)s;
    int n = cbMax < AZOTH_TICKET_LEN ? cbMax : AZOTH_TICKET_LEN;
    if (n < 0) n = 0;
    if (buf && n > 0) memset(buf, AZOTH_TICKET_BYTE, (size_t)n);
    if (pcb) *pcb = (uint32_t)n;
    log_line("GetAuthSessionTicket", "");
    return (void *)(uintptr_t)1; /* HAuthTicket 1 = valid handle */
}
static uint32_t __fastcall u_GetVoiceOptimalSampleRate(void *s) { (void)s; TRACE_ONCE("User:VoiceSampleRate"); return 11025; }
static uint8_t __fastcall u_GetUserDataFolder(void *s, char *buf, int cub) {
    (void)s;
    log_line("GetUserDataFolder", "");
    if (buf && cub > 4) {
        DWORD n = GetTempPathA((DWORD)cub, buf);
        return (n > 0 && n < (DWORD)cub) ? 1 : 0;
    }
    return 0;
}

/* Fake async ticket handles: Omni login needs them to proceed locally. */
#define FAKE_CALL ((uint64_t)0xA20A20AULL)
static uint64_t __fastcall u_RequestEncryptedAppTicket(void *s, void *d, int n) {
    (void)s; (void)d; (void)n;
    log_line("RequestEncryptedAppTicket", "fake-handle");
    return FAKE_CALL;
}
static uint8_t __fastcall u_GetEncryptedAppTicket(void *s, void *t, int cbMax, uint32_t *pcb) {
    (void)s;
    int n = cbMax < AZOTH_TICKET_LEN ? cbMax : AZOTH_TICKET_LEN;
    if (n < 0) n = 0;
    if (t && n > 0) memset(t, AZOTH_TICKET_BYTE, (size_t)n);
    if (pcb) *pcb = (uint32_t)n;
    log_line("GetEncryptedAppTicket", "fake-ok");
    return 1;
}
/* The game calls GetAuthTicketForWebApi on EVERY login attempt but registers
 * the 168 callback only once. Fire-once semantics wedge all retries at
 * "Getting steam auth session ticket". Fix: each ticket request arms a
 * pending flag; the next RunCallbacks pump delivers it. The ticket bytes
 * are static, so a spare delivery is harmless. */
static volatile int g_webapi_ticket_pending = 0;
static uint64_t __fastcall u_GetAuthTicketForWebApi(void *s, const char *id) {
    (void)s;
    log_line("GetAuthTicketForWebApi", id ? id : "(null)");
    g_webapi_ticket_pending = 1;
    return FAKE_CALL;
}

/* --- ISteamFriends017 (80 methods, SDK order) --- */
static const char *__fastcall f_GetPersonaName(void *s) { (void)s; TRACE_ONCE("Friends:GetPersonaName"); return k_persona; }
static int __fastcall f_GetPersonaState(void *s) { (void)s; TRACE_ONCE("Friends:PersonaState"); return 1; }
static uint64_t __fastcall f_GetFriendByIndex(void *s, int i, int flags) {
    (void)s; (void)i; (void)flags; return 0; /* invalid CSteamID */
}
static uint64_t __fastcall f_GetClanByIndex(void *s, int i) { (void)s; TRACE_ONCE("call:f_GetClanByIndex"); (void)i; return 0; }
static uint64_t __fastcall f_GetClanOwner(void *s, uint64_t clan) { (void)s; TRACE_ONCE("call:f_GetClanOwner"); (void)clan; return 0; }

/* --- ISteamUtils010 (39 methods, SDK order) --- */
static uint32_t __fastcall w_Seconds(void *s) { (void)s; TRACE_ONCE("call:w_Seconds"); return 100; }
static int __fastcall w_Universe(void *s) { (void)s; TRACE_ONCE("call:w_Universe"); return 1; } /* k_EUniversePublic */
static uint32_t __fastcall w_ServerTime(void *s) { (void)s; TRACE_ONCE("call:w_ServerTime"); return (uint32_t)time(NULL); }
static const char *__fastcall w_IPCountry(void *s) { (void)s; TRACE_ONCE("Utils:IPCountry"); return k_country; }
static const char *__fastcall w_UILanguage(void *s) { (void)s; TRACE_ONCE("call:w_UILanguage"); return k_lang; }
static uint8_t __fastcall w_Battery(void *s) { (void)s; TRACE_ONCE("Utils:Battery"); return 255; } /* on AC */
static uint32_t __fastcall w_AppID(void *s) { (void)s; TRACE_ONCE("Utils:GetAppID"); return AZOTH_APPID; }
static uint8_t __fastcall w_IsAPICallCompleted(void *s, uint64_t call, uint8_t *failed) {
    (void)s;
    if (failed) *failed = 0;
    if (call == FAKE_CALL) return 1;
    return 1;
}
static uint8_t __fastcall w_GetAPICallResult(void *s, uint64_t call, void *cb, int cub, int exp, uint8_t *failed) {
    (void)s; (void)exp;
    if (call == FAKE_CALL && cb && cub >= 4) {
        /* Fake OK payload: most result structs start with EResult; 1 = k_EResultOK. */
        *(int32_t *)cb = 1;
        if (cub >= 8) *((int32_t *)cb + 1) = 0;
        if (failed) *failed = 0;
        log_line("GetAPICallResult", "fake-ok");
        return 1;
    }
    if (failed) *failed = 1;
    return 0;
}

/* --- tiny ISteamApps008 fallback (game barely touches it; safe stubs).
 * Order follows the SDK so string slots never return NULL. --- */
static uint8_t __fastcall a_BIsSubscribed(void *s) { (void)s; TRACE_ONCE("Apps:BIsSubscribed"); return 1; }
static uint8_t __fastcall a_BIsSubscribedApp(void *s, uint32_t app) { (void)s; (void)app; TRACE_ONCE("Apps:BIsSubscribedApp"); return 1; }
static const char *__fastcall a_GetCurrentGameLanguage(void *s) { (void)s; TRACE_ONCE("Apps:GetCurrentGameLanguage"); return k_lang; }
static const char *__fastcall a_GetAvailableGameLanguages(void *s) { (void)s; TRACE_ONCE("call:a_GetAvailableGameLanguages"); return k_lang; }
static uint64_t __fastcall a_GetAppOwner(void *s) { (void)s; TRACE_ONCE("call:a_GetAppOwner"); return AZOTH_STEAMID; }
static const char *__fastcall a_GetBetaName(void *s) { (void)s; TRACE_ONCE("Apps:GetBetaName"); return k_empty; }
static const char *__fastcall a_GetLaunchQueryParam(void *s, const char *k) { (void)s; TRACE_ONCE("call:a_GetLaunchQueryParam"); (void)k; return k_empty; }
static uint32_t __fastcall a_GetAppInstallDir(void *s, uint32_t app, char *buf, uint32_t cub) {
    (void)s; (void)app;
    TRACE_ONCE("Apps:GetAppInstallDir");
    if (buf && cub > 0) buf[0] = '\0';
    return 1; /* size of "" incl. nul: "not found" without crashing on NULL */
}

/* ------------------------------------------------------------- objects --- */
/* vtable = array of function pointers; object = pointer to vtable.
 * Sizes follow the SDK headers exactly (User023=33, Friends017=80,
 * Utils010=39). Apps008 is only a fallback the game barely touches, so it
 * gets a generous 64 slots — a short table here would be an out-of-bounds
 * jump the moment the game calls past its end. */

#define N_USER 33
#define N_FRIENDS 80
#define N_UTILS 39
#define N_APPS 64

static void *g_vt_user[N_USER];
static void *g_vt_friends[N_FRIENDS];
static void *g_vt_utils[N_UTILS];
static void *g_vt_apps[N_APPS];
static void *g_obj_user, *g_obj_friends, *g_obj_utils, *g_obj_apps;
static int g_vt_ready = 0;

static void build_vtables(void) {
    if (g_vt_ready) return;
    size_t i;
    /* default everything to safe zero/empty, then override meaningful slots */
    for (i = 0; i < N_USER; i++) g_vt_user[i] = (void *)u_def;
    for (i = 0; i < N_FRIENDS; i++) g_vt_friends[i] = (void *)f_def;
    for (i = 0; i < N_UTILS; i++) g_vt_utils[i] = (void *)w_def;
    for (i = 0; i < N_APPS; i++) g_vt_apps[i] = (void *)a_def;

    /* User023 */
    g_vt_user[0] = (void *)u_GetHSteamUser;
    g_vt_user[1] = (void *)u_BLoggedOn;
    g_vt_user[2] = (void *)u_GetSteamID;
    /* 3..5 deprecated/void stay 0/void-safe (return 0 harmless) */
    g_vt_user[5] = (void *)t_void;
    g_vt_user[6] = (void *)u_GetUserDataFolder;
    g_vt_user[7] = (void *)t_void;
    g_vt_user[8] = (void *)t_void;
    g_vt_user[12] = (void *)u_GetVoiceOptimalSampleRate;
    g_vt_user[13] = (void *)u_Ticket;
    g_vt_user[14] = (void *)u_GetAuthTicketForWebApi;
    g_vt_user[16] = (void *)t_void; /* EndAuthSession */
    g_vt_user[17] = (void *)t_void; /* CancelAuthTicket */
    g_vt_user[20] = (void *)t_void; /* AdvertiseGame */
    g_vt_user[21] = (void *)u_RequestEncryptedAppTicket;
    g_vt_user[22] = (void *)u_GetEncryptedAppTicket;

    /* Friends017: string returns must never be NULL (except documented nickname) */
    g_vt_friends[0] = (void *)f_GetPersonaName;
    g_vt_friends[2] = (void *)f_GetPersonaState;
    g_vt_friends[4] = (void *)f_GetFriendByIndex;
    g_vt_friends[7] = (void *)t_str_empty;  /* GetFriendPersonaName -> "" */
    g_vt_friends[9] = (void *)t_str_empty;  /* history -> "" */
    g_vt_friends[11] = (void *)t_str_empty;  /* nickname -> "" (NULL allowed but "" never crashes) */
    g_vt_friends[14] = (void *)t_str_empty; /* group name -> "" */
    g_vt_friends[19] = (void *)f_GetClanByIndex;
    g_vt_friends[20] = (void *)t_str_empty; /* GetClanName -> "" */
    g_vt_friends[21] = (void *)t_str_empty; /* GetClanTag -> "" */
    g_vt_friends[27] = (void *)t_void;
    g_vt_friends[28] = (void *)t_void;
    g_vt_friends[29] = (void *)t_void;
    g_vt_friends[30] = (void *)t_void;
    g_vt_friends[31] = (void *)t_void;
    g_vt_friends[32] = (void *)t_void;
    g_vt_friends[33] = (void *)t_void;
    g_vt_friends[39] = (void *)f_GetClanOwner;
    g_vt_friends[43] = (void *)t_u64_1;     /* SetRichPresence -> true */
    g_vt_friends[44] = (void *)t_void;      /* ClearRichPresence */
    g_vt_friends[45] = (void *)t_str_empty; /* GetFriendRichPresence -> "" */
    g_vt_friends[47] = (void *)t_str_empty;
    g_vt_friends[48] = (void *)t_void;
    /* remaining bool/count stay 0 = false/none (safe: no friends) */

    /* Utils010 */
    g_vt_utils[0] = (void *)w_Seconds;
    g_vt_utils[1] = (void *)w_Seconds;
    g_vt_utils[2] = (void *)w_Universe;
    g_vt_utils[3] = (void *)w_ServerTime;
    g_vt_utils[4] = (void *)w_IPCountry;
    g_vt_utils[8] = (void *)w_Battery;
    g_vt_utils[9] = (void *)w_AppID;
    g_vt_utils[10] = (void *)t_void;
    g_vt_utils[11] = (void *)w_IsAPICallCompleted;
    g_vt_utils[13] = (void *)w_GetAPICallResult;
    g_vt_utils[14] = (void *)t_void; /* RunFrame */
    g_vt_utils[23] = (void *)w_UILanguage;
    g_vt_utils[25] = (void *)t_void;
    g_vt_utils[27] = (void *)t_void;
    g_vt_utils[29] = (void *)t_void;
    g_vt_utils[36] = (void *)t_void;

    /* Apps008 fallback in real SDK order: strings must never be NULL. */
    g_vt_apps[0] = (void *)a_BIsSubscribed;          /* BIsSubscribed -> true */
    /* [1] BIsLowViolence, [2] BIsCybercafe, [3] BIsVACBanned -> false (a_def) */
    g_vt_apps[4] = (void *)a_GetCurrentGameLanguage; /* -> "english" */
    g_vt_apps[5] = (void *)a_GetAvailableGameLanguages;
    g_vt_apps[6] = (void *)a_BIsSubscribedApp;       /* -> true */
    g_vt_apps[7] = (void *)a_BIsSubscribedApp;       /* BIsDlcInstalled -> true */
    g_vt_apps[19] = (void *)a_BIsSubscribedApp;      /* BIsAppInstalled -> true */
    g_vt_apps[20] = (void *)a_GetAppOwner;           /* GetAppOwner -> fake SteamID */
    g_vt_apps[14] = (void *)a_GetBetaName;           /* GetCurrentBetaName -> "" (never NULL) */
    g_vt_apps[18] = (void *)a_GetAppInstallDir;      /* -> "" with size 1 */
    g_vt_apps[21] = (void *)a_GetLaunchQueryParam;   /* -> "" */

    g_obj_user = (void *)&g_vt_user;
    g_obj_friends = (void *)&g_vt_friends;
    g_obj_utils = (void *)&g_vt_utils;
    g_obj_apps = (void *)&g_vt_apps;
    /* objects are "pointer to vtable": store vtable addr in static then hand &static */
    static void *o_u, *o_f, *o_w, *o_a;
    o_u = g_vt_user; o_f = g_vt_friends; o_w = g_vt_utils; o_a = g_vt_apps;
    g_obj_user = &o_u; g_obj_friends = &o_f; g_obj_utils = &o_w; g_obj_apps = &o_a;
    g_vt_ready = 1;
}

static void *iface_for(const char *ver) {
    build_vtables();
    if (!ver) return g_obj_utils;
    if (strstr(ver, "SteamUser")) return g_obj_user;
    if (strstr(ver, "SteamFriends")) return g_obj_friends;
    if (strstr(ver, "SteamUtils")) return g_obj_utils;
    if (strstr(ver, "SteamApps") || strstr(ver, "STEAMAPPS")) return g_obj_apps;
    log_line("unknown-iface", ver);
    return g_obj_utils;
}

/* ------------------------------------------------------- flat exports --- */

/* Minimal Steam callback dispatch: the game registers CCallbackBase objects
 * (vtable: Run(param), Run(param,iofail,call), Size()) and waits for async
 * completions inside SteamAPI_RunCallbacks. Firing 101/163/168 once each is
 * what unblocks the Omni login (observed: "Getting steam auth session ticket"
 * retried every 10 s until 163 is dispatched). */
#define MAX_CBS 32
static struct { void *obj; int id; int fired; } g_cbs[MAX_CBS];
static int g_ncb = 0;

typedef void (__fastcall *cb_run_fn)(void *self, void *param);

static void fire_cb(void *obj, void *param) {
    void **vt = *(void ***)obj;
    ((cb_run_fn)vt[0])(obj, param);
}

API uint8_t SteamAPI_Init(void) { build_vtables(); log_line("SteamAPI_Init", "ok"); return 1; }
API uint8_t SteamAPI_InitSafe(void) { return SteamAPI_Init(); }
API uint8_t SteamAPI_InitAnonymousUser(void) { return SteamAPI_Init(); }
API void SteamAPI_Shutdown(void) {}
API uint8_t SteamAPI_IsSteamRunning(void) { return 1; }
API uint8_t SteamAPI_RestartAppIfNecessary(uint32_t app) { (void)app; return 0; }
API void SteamAPI_RunCallbacks(void) {
    TRACE_ONCE("RunCallbacks");
    for (int i = 0; i < g_ncb; i++) {
        if (!g_cbs[i].obj) continue;
        int id = g_cbs[i].id;
        if (g_cbs[i].fired && !(id == 168 && g_webapi_ticket_pending)) continue;
        if (id == 101) { /* SteamServersConnected_t: empty struct */
            uint8_t ev = 0;
            fire_cb(g_cbs[i].obj, &ev);
            g_cbs[i].fired = 1;
            log_line("FireCallback", "101 connected");
        } else if (id == 163) { /* GetAuthSessionTicketResponse_t {u32 ticket; u32 result} */
            struct { uint32_t h; uint32_t r; } ev = {1, 1}; /* handle 1, k_EResultOK */
            fire_cb(g_cbs[i].obj, &ev);
            g_cbs[i].fired = 1;
            log_line("FireCallback", "163 ticket-ok");
        } else if (id == 168) { /* GetTicketForWebApiResponse_t */
            /* Real webapi tickets are ~1 KB blobs, not 32 B. A tiny ticket
             * dies locally in Omni CreateSession (result 201); try 1024. */
            static uint8_t ev[1100];
            *(uint32_t *)(ev + 0) = (uint32_t)(FAKE_CALL & 0xffffffffu);
            *(uint32_t *)(ev + 4) = 1; /* k_EResultOK */
            *(uint32_t *)(ev + 8) = 1024;
            memset(ev + 12, AZOTH_TICKET_BYTE, 1024);
            fire_cb(g_cbs[i].obj, ev);
            g_cbs[i].fired = 1;
            g_webapi_ticket_pending = 0;
            log_line("FireCallback", "168 webapi-ok");
        }
    }
}
API void SteamAPI_ReleaseCurrentThreadMemory(void) {}
API int SteamAPI_GetHSteamUser(void) { return 1; }
API int SteamAPI_GetHSteamPipe(void) { return 1; }
static char cb_buf[64];
API void SteamAPI_RegisterCallback(void *p, int i) {
    if (p && g_ncb < MAX_CBS) {
        int dup = 0;
        for (int k = 0; k < g_ncb; k++)
            if (g_cbs[k].obj == p && g_cbs[k].id == i) {
                dup = 1;
                /* Re-arm: the game re-registers when it wants a FRESH async
                 * result (login retry, second sign-in). Without this, retries
                 * stall forever at "Getting steam auth session ticket". */
                g_cbs[k].fired = 0;
                break;
            }
        if (!dup) { g_cbs[g_ncb].obj = p; g_cbs[g_ncb].id = i; g_cbs[g_ncb].fired = 0; g_ncb++; }
    }
    _snprintf_s(cb_buf, sizeof(cb_buf), _TRUNCATE, "id=%d ptr=%p", i, p);
    log_line("RegisterCallback", cb_buf);
}
API void SteamAPI_UnregisterCallback(void *p) {
    (void)p;
    TRACE_ONCE("UnregisterCallback");
    if (!p) return;
    for (int k = 0; k < g_ncb; k++)
        if (g_cbs[k].obj == p) g_cbs[k].obj = NULL;
}
API void SteamAPI_RegisterCallResult(void *p, uint64_t h) { (void)p; (void)h; }
API void SteamAPI_UnregisterCallResult(void *p, uint64_t h) { (void)p; (void)h; }

typedef void (*ctx_fn)(void *);
struct ctx_init { ctx_fn fn; uintptr_t counter; };

API void *SteamInternal_ContextInit(void *p) {
    struct ctx_init *c = (struct ctx_init *)p;
    build_vtables();
    if (c->counter == 0) {
        c->fn((void *)(c + 1));
        c->counter = 1;
    }
    return (void *)(c + 1);
}

API void *SteamInternal_CreateInterface(const char *ver) {
    log_line("CreateInterface", ver ? ver : "(null)");
    return iface_for(ver);
}
API void *SteamInternal_FindOrCreateUserInterface(int user, const char *ver) {
    (void)user;
    log_line("FindOrCreateUser", ver ? ver : "(null)");
    return iface_for(ver);
}
API void *SteamInternal_FindOrCreateGameServerInterface(int user, const char *ver) {
    (void)user;
    log_line("FindOrCreateGameServer", ver ? ver : "(null)");
    return iface_for(ver);
}

API void *SteamAPI_SteamUser_v023(void) { build_vtables(); return g_obj_user; }
API void *SteamAPI_SteamFriends_v017(void) { build_vtables(); return g_obj_friends; }
API void *SteamAPI_SteamUtils_v010(void) { build_vtables(); return g_obj_utils; }
API void *SteamAPI_SteamApps_v008(void) { build_vtables(); return g_obj_apps; }

BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID x) { (void)h; (void)x; (void)r; return TRUE; }
