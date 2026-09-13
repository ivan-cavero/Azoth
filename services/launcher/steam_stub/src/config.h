// Azoth steam stub — shared constants (private launch only).
// Never copy over the Steam install DLL. Used only in %LOCALAPPDATA%\Azoth\game\Bin64\.
#pragma once
#include <stdint.h>

#define AZOTH_APPID ((uint32_t)1063730u)
#define AZOTH_STEAMID ((uint64_t)76561197960287930ull)

#define AZOTH_PERSONA "AzothPlayer"
#define AZOTH_LANG "english"
#define AZOTH_COUNTRY "US"

// Dummy auth ticket: only our gateway ever sees it. Invalid on Amazon.
#define AZOTH_TICKET_BYTE 0xA5
#define AZOTH_TICKET_LEN 32
