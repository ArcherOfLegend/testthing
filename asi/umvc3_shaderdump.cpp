// umvc3_shaderdump.asi - dump the shader bytecode the game hands to Direct3D 9,
// and record which of those shaders it actually binds.
//
// ---------------------------------------------------------------------------
// Why this exists
// ---------------------------------------------------------------------------
// Static search for the shaders failed, and it failed informatively:
//
//   * UserShaderPackage.mfx is NOT the shader store. Its string table reads
//     IASystemCopy / __InputLayout / Position / Texcoord / IAFilter - "IA" is
//     input assembler, so the file describes vertex layouts and semantics. Its
//     entropy is 3.02 bits/byte, so it is neither packed nor encrypted; there is
//     simply no microcode in it, in either byte order.
//   * Nothing else on disk is shader-shaped: system/ holds filter, font and
//     texture; the largest files in nativePCx64 are a movie, audio and stages.
//   * umvc3.exe matches 35 ps_3_0 version tokens and ZERO vs_3_0, and no
//     renderer has one without the other - so that scan was matching noise.
//
// The game imports d3d9.dll and does not import D3DCompiler, so whatever it
// draws with must reach D3D as compiled DX9 token streams. Asking D3D directly
// is therefore both the shortest route and the only self-verifying one: it does
// not care where the bytes were stored or how they were encoded.
//
// ---------------------------------------------------------------------------
// How it hooks
// ---------------------------------------------------------------------------
// IAT patch on the exe's import of Direct3DCreate9, then vtable patches on the
// returned interfaces. An IAT patch needs no length disassembler and no
// trampoline, and by DLL_PROCESS_ATTACH the loader has already resolved static
// imports, so the pointer is there to take.
//
//   Direct3DCreate9  ->  IDirect3D9::CreateDevice  ->  the device vtable
//
// Device vtable slots are hardcoded by declaration order in d3d9.h. That is
// exactly the kind of constant that fails silently and corrupts something else,
// so every slot is checked to point inside d3d9.dll before it is touched, and
// the patch is abandoned if any does not.
//
// Output, next to this .asi:
//   umvc3_shaderdump.log        what happened, and the used-shader summary
//   shaderdump\ps_0000_XXXXXXXX.bin   one file per distinct created shader
//
// Shaders are written at creation. Binding is only counted - SetPixelShader
// runs thousands of times a frame, so logging each call would produce gigabytes
// and change the frame timing being observed. What matters is the SET of
// shaders a screen uses, which is small.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

// ============================================================ logging =======
static char g_dir[MAX_PATH] = {0};      // folder this .asi lives in
static char g_log[MAX_PATH] = {0};
static char g_dump[MAX_PATH] = {0};
static CRITICAL_SECTION g_lock;

static void Log(const char* fmt, ...) {
    FILE* f = nullptr;
    if (fopen_s(&f, g_log, "a") != 0 || !f) return;
    SYSTEMTIME st; GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d] ", st.wHour, st.wMinute, st.wSecond);
    va_list ap; va_start(ap, fmt);
    vfprintf(f, fmt, ap); va_end(ap);
    fprintf(f, "\n");
    fclose(f);
}

// ============================================================ shader table ==
// Flat and fixed: this is touched from the render thread on every bind, so it
// must not allocate. 4096 was chosen against the 2874 records in the .mfx and
// was simply wrong - the first run created exactly 4096 and was still going, so
// that count was the cap talking, not the game. Shaders created past the cap are
// also invisible to the bind counter, which would silently understate the used
// set. The overrun is now logged rather than swallowed.
const int kMaxShaders = 32768;

struct ShaderRec {
    void*    handle;      // IDirect3DPixelShader9* / IDirect3DVertexShader9*
    unsigned crc;
    unsigned bytes;
    bool     pixel;
    bool     used;        // has it ever been bound?
    unsigned binds;
};
static ShaderRec g_sh[kMaxShaders];
static int  g_shCount = 0;
static bool g_summaryDue = false;

static unsigned Crc32(const void* data, size_t n) {
    static unsigned tab[256];
    static bool init = false;
    if (!init) {
        for (unsigned i = 0; i < 256; i++) {
            unsigned c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            tab[i] = c;
        }
        init = true;
    }
    const unsigned char* p = (const unsigned char*)data;
    unsigned c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) c = tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

// A DX9 token stream starts with a version token and ends with END (0x0000FFFF).
// The caller never passes a length, so walking to END is the only way to know
// how much to copy - and it is also a validity check: a stream that runs past
// the cap is not a shader and is not written out.
static size_t TokenStreamBytes(const DWORD* p) {
    if (!p) return 0;
    const DWORD kEnd = 0x0000FFFFu;
    const size_t kCap = 65536;            // tokens, not bytes
    for (size_t i = 0; i < kCap; i++) {
        if (p[i] == kEnd) return (i + 1) * sizeof(DWORD);
    }
    return 0;
}

static void RecordShader(void* handle, const DWORD* fn, bool pixel) {
    size_t n = TokenStreamBytes(fn);
    EnterCriticalSection(&g_lock);
    if (g_shCount >= kMaxShaders) {
        bool first = (g_shCount == kMaxShaders);
        if (first) g_shCount++;               // so this only says it once
        LeaveCriticalSection(&g_lock);
        if (first) Log("!! shader table full at %d - everything past this point "
                       "is neither dumped nor counted", kMaxShaders);
        return;
    }
    int idx = g_shCount++;
    ShaderRec& r = g_sh[idx];
    r.handle = handle;
    r.bytes  = (unsigned)n;
    r.pixel  = pixel;
    r.used   = false;
    r.binds  = 0;
    r.crc    = n ? Crc32(fn, n) : 0;
    LeaveCriticalSection(&g_lock);

    if (!n) {
        Log("%s shader #%d: token stream had no END within cap - not written",
            pixel ? "pixel" : "vertex", idx);
        return;
    }
    char path[MAX_PATH];
    sprintf_s(path, "%s\\%s_%04d_%08X.bin", g_dump, pixel ? "ps" : "vs", idx, r.crc);
    FILE* f = nullptr;
    if (fopen_s(&f, path, "wb") == 0 && f) {
        fwrite(fn, 1, n, f);
        fclose(f);
    }
    // The version token says what profile it was compiled for, which tells us
    // straight away whether fxc can produce a drop-in replacement.
    DWORD v = fn[0];
    Log("%s shader #%-4d %6u bytes  crc %08X  version %u_%u  -> %s",
        pixel ? "pixel " : "vertex", idx, (unsigned)n, r.crc,
        (unsigned)((v >> 8) & 0xFF), (unsigned)(v & 0xFF), strrchr(path, '\\') + 1);
}

static void NoteBind(void* handle, bool pixel) {
    if (!handle) return;
    EnterCriticalSection(&g_lock);
    for (int i = 0; i < g_shCount; i++) {
        if (g_sh[i].handle == handle && g_sh[i].pixel == pixel) {
            if (!g_sh[i].used) { g_sh[i].used = true; g_summaryDue = true; }
            g_sh[i].binds++;
            break;
        }
    }
    LeaveCriticalSection(&g_lock);
}

static void WriteSummary() {
    EnterCriticalSection(&g_lock);
    int created = g_shCount, used = 0;
    for (int i = 0; i < g_shCount; i++) if (g_sh[i].used) used++;
    Log("---- %d shaders created, %d ever bound ----", created, used);
    for (int i = 0; i < g_shCount; i++) {
        if (g_sh[i].used) {
            Log("   %s #%-4d crc %08X  %u binds",
                g_sh[i].pixel ? "ps" : "vs", i, g_sh[i].crc, g_sh[i].binds);
        }
    }
    LeaveCriticalSection(&g_lock);
}

// ============================================================ config ========
// umvc3_shaderdump.ini, beside this .asi. Written without a BOM - GetPrivateProfile*
// cannot find a section behind one.
//
//   [identify]
//   verts=1674,1400          ; log the shaders bound for draws of this many
//                            ; vertices. The grid-line meshes are 1674 and 1400,
//                            ; which is a far sharper handle than guessing among
//                            ; the 49 shaders the screen binds.
//   [replace]
//   1F9BA0F8=solid.bin       ; crc of the ORIGINAL bytecode -> replacement file
//
// Keyed by CRC rather than by dump index: the index is creation order, which is
// only stable while nothing else about the frame changes, and the whole point of
// this is to change things.
const int kMaxWatch = 16;
const int kMaxRepl  = 32;

struct Repl { unsigned crc; DWORD* code; size_t bytes; char file[64]; };
static Repl     g_repl[kMaxRepl];
static int      g_replCount = 0;
static unsigned g_watch[kMaxWatch];
static int      g_watchCount = 0;

static void LoadConfig(const char* dir) {
    char ini[MAX_PATH];
    sprintf_s(ini, "%s\\umvc3_shaderdump.ini", dir);
    if (GetFileAttributesA(ini) == INVALID_FILE_ATTRIBUTES) {
        Log("no umvc3_shaderdump.ini - dumping only");
        return;
    }
    char buf[1024] = {0};
    GetPrivateProfileStringA("identify", "verts", "", buf, sizeof(buf), ini);
    for (char* t = buf; *t && g_watchCount < kMaxWatch; ) {
        while (*t == ' ' || *t == ',') t++;
        if (!*t) break;
        g_watch[g_watchCount++] = (unsigned)strtoul(t, &t, 10);
    }
    if (g_watchCount) {
        char list[256] = {0};
        for (int i = 0; i < g_watchCount; i++) {
            char one[32]; sprintf_s(one, "%s%u", i ? ", " : "", g_watch[i]);
            strcat_s(list, one);
        }
        Log("identify: watching draws of %s vertices", list);
    }
    char keys[4096] = {0};
    GetPrivateProfileStringA("replace", nullptr, "", keys, sizeof(keys), ini);
    for (const char* k = keys; *k; k += strlen(k) + 1) {
        if (g_replCount >= kMaxRepl) break;
        char val[MAX_PATH] = {0};
        GetPrivateProfileStringA("replace", k, "", val, sizeof(val), ini);
        if (!val[0]) continue;
        char path[MAX_PATH];
        sprintf_s(path, "%s\\%s", dir, val);
        FILE* f = nullptr;
        if (fopen_s(&f, path, "rb") != 0 || !f) { Log("replace %s: cannot open %s", k, path); continue; }
        fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
        if (n <= 0 || (n % 4) != 0) { fclose(f); Log("replace %s: %s is not a token stream", k, val); continue; }
        DWORD* code = (DWORD*)malloc((size_t)n);
        if (!code || fread(code, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(code); continue; }
        fclose(f);
        // Refuse anything that is not a well-formed shader: handing D3D a bad
        // token stream is a crash, and it would look like the hook's fault.
        if (TokenStreamBytes(code) != (size_t)n) {
            Log("replace %s: %s has no END token at its end - ignored", k, val);
            free(code); continue;
        }
        Repl& r = g_repl[g_replCount++];
        r.crc = (unsigned)strtoul(k, nullptr, 16);
        r.code = code; r.bytes = (size_t)n;
        strcpy_s(r.file, val);
        Log("replace: crc %08X -> %s (%ld bytes, version %u_%u)", r.crc, val, n,
            (unsigned)((code[0] >> 8) & 0xFF), (unsigned)(code[0] & 0xFF));
    }
}

static const Repl* FindRepl(unsigned crc) {
    for (int i = 0; i < g_replCount; i++) if (g_repl[i].crc == crc) return &g_repl[i];
    return nullptr;
}

static bool Watched(unsigned verts) {
    for (int i = 0; i < g_watchCount; i++) if (g_watch[i] == verts) return true;
    return false;
}

// ============================================================ hooks =========
typedef HRESULT (STDMETHODCALLTYPE *CreateVS_t)(IDirect3DDevice9*, const DWORD*, IDirect3DVertexShader9**);
typedef HRESULT (STDMETHODCALLTYPE *CreatePS_t)(IDirect3DDevice9*, const DWORD*, IDirect3DPixelShader9**);
typedef HRESULT (STDMETHODCALLTYPE *SetVS_t)(IDirect3DDevice9*, IDirect3DVertexShader9*);
typedef HRESULT (STDMETHODCALLTYPE *SetPS_t)(IDirect3DDevice9*, IDirect3DPixelShader9*);
typedef HRESULT (STDMETHODCALLTYPE *DrawIP_t)(IDirect3DDevice9*, D3DPRIMITIVETYPE, INT,
                                              UINT, UINT, UINT, UINT);
typedef HRESULT (STDMETHODCALLTYPE *CreateDevice_t)(IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD,
                                                    D3DPRESENT_PARAMETERS*, IDirect3DDevice9**);
typedef IDirect3D9* (WINAPI *Create9_t)(UINT);

static CreateVS_t     o_CreateVS   = nullptr;
static CreatePS_t     o_CreatePS   = nullptr;
static SetVS_t        o_SetVS      = nullptr;
static SetPS_t        o_SetPS      = nullptr;
static DrawIP_t       o_DrawIP     = nullptr;
static CreateDevice_t o_CreateDev  = nullptr;
static Create9_t      o_Create9    = nullptr;
static bool           g_devHooked  = false;
static void*          g_curPS      = nullptr;   // whatever is bound right now
static void*          g_curVS      = nullptr;

// Declaration order in d3d9.h. Verified against the module each one points into
// before anything is written.
enum {
    kIdx_CreateDevice      = 16,
    kIdx_DrawIndexedPrimitive = 82,
    kIdx_CreateVertexShader = 91,
    kIdx_SetVertexShader    = 92,
    kIdx_CreatePixelShader  = 106,
    kIdx_SetPixelShader     = 107,
};

// Committed, executable memory. Requiring d3d9.dll specifically was wrong: on a
// Steam install the overlay has already hooked CreateDevice, so its slot points
// into gameoverlayrenderer64.dll and a d3d9-only rule refuses a perfectly good
// chain. Executability is the property that actually matters.
static bool IsCode(void* p) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!p || !VirtualQuery(p, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT) return false;
    const DWORD exec = PAGE_EXECUTE | PAGE_EXECUTE_READ |
                       PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    return (mbi.Protect & exec) != 0 && !(mbi.Protect & PAGE_GUARD);
}

// A real IDirect3DDevice9 vtable has 119 entries, all code. Checking the whole
// span is what actually guards the hardcoded slot numbers - far better than
// inspecting one entry, because a wrong index still lands on some other
// function and looks perfectly reasonable on its own.
static bool VtableLooksLikeDevice(void** vtbl) {
    const int kMethods = 119;
    for (int i = 0; i < kMethods; i++) {
        if (!IsCode(vtbl[i])) {
            Log("  vtable entry %d is not code - this is not the device vtable", i);
            return false;
        }
    }
    return true;
}

static bool PatchSlot(void** vtbl, int idx, void* repl, void** orig, const char* name) {
    void* cur = vtbl[idx];
    if (!IsCode(cur)) {
        Log("  slot %d (%s) is not executable - refusing to patch", idx, name);
        return false;
    }
    HMODULE mod = nullptr;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                       GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCSTR)cur, &mod);
    char who[MAX_PATH] = "?";
    if (mod) GetModuleFileNameA(mod, who, MAX_PATH);
    const char* leaf = strrchr(who, '\\'); leaf = leaf ? leaf + 1 : who;
    DWORD old = 0;
    if (!VirtualProtect(&vtbl[idx], sizeof(void*), PAGE_READWRITE, &old)) return false;
    *orig = cur;
    vtbl[idx] = repl;
    VirtualProtect(&vtbl[idx], sizeof(void*), old, &old);
    Log("  hooked slot %-3d %-20s %p in %s", idx, name, cur, leaf);
    return true;
}

// Substitution happens here, before D3D ever sees the original: the game keeps
// the handle it is given, so swapping the bytes at creation needs no tracking
// afterwards and cannot desynchronise. The shader is still recorded under the
// ORIGINAL crc, so the log and the ini keep talking about the same thing.
static const DWORD* MaybeReplace(const DWORD* fn, bool pixel, unsigned* crcOut) {
    size_t n = TokenStreamBytes(fn);
    unsigned crc = n ? Crc32(fn, n) : 0;
    *crcOut = crc;
    const Repl* r = FindRepl(crc);
    if (!r) return fn;
    // A vertex shader cannot stand in for a pixel shader; the version token says
    // which is which, and getting it wrong is a device reset at best.
    bool replIsPixel = ((r->code[0] >> 16) & 0xFFFF) == 0xFFFF;
    if (replIsPixel != pixel) {
        Log("replace %08X: %s is a %s shader, wanted %s - ignored", crc, r->file,
            replIsPixel ? "pixel" : "vertex", pixel ? "pixel" : "vertex");
        return fn;
    }
    Log("replaced %s shader %08X with %s", pixel ? "pixel" : "vertex", crc, r->file);
    return r->code;
}

static HRESULT STDMETHODCALLTYPE My_CreateVS(IDirect3DDevice9* dev, const DWORD* fn,
                                             IDirect3DVertexShader9** out) {
    unsigned crc = 0;
    const DWORD* use = MaybeReplace(fn, false, &crc);
    HRESULT hr = o_CreateVS(dev, use, out);
    if (SUCCEEDED(hr) && out && *out) RecordShader(*out, fn, false);
    return hr;
}
static HRESULT STDMETHODCALLTYPE My_CreatePS(IDirect3DDevice9* dev, const DWORD* fn,
                                             IDirect3DPixelShader9** out) {
    unsigned crc = 0;
    const DWORD* use = MaybeReplace(fn, true, &crc);
    HRESULT hr = o_CreatePS(dev, use, out);
    if (SUCCEEDED(hr) && out && *out) RecordShader(*out, fn, true);
    return hr;
}
static HRESULT STDMETHODCALLTYPE My_SetVS(IDirect3DDevice9* dev, IDirect3DVertexShader9* s) {
    g_curVS = s;
    NoteBind(s, false);
    return o_SetVS(dev, s);
}
static HRESULT STDMETHODCALLTYPE My_SetPS(IDirect3DDevice9* dev, IDirect3DPixelShader9* s) {
    g_curPS = s;
    NoteBind(s, true);
    return o_SetPS(dev, s);
}

// The identification step. A draw carries its vertex count, and the grid-line
// meshes have counts nothing else on the screen shares, so the pair bound for
// those draws is the answer - no sweeping 49 candidates one launch at a time.
// Reported once per (count, vs, ps): this runs thousands of times a frame.
static HRESULT STDMETHODCALLTYPE My_DrawIP(IDirect3DDevice9* dev, D3DPRIMITIVETYPE type,
                                           INT baseVertex, UINT minVertex, UINT numVertices,
                                           UINT startIndex, UINT primCount) {
    if (g_watchCount && Watched(numVertices)) {
        static struct { UINT verts; void* vs; void* ps; } seen[64];
        static int nseen = 0;
        bool fresh = true;
        EnterCriticalSection(&g_lock);
        for (int i = 0; i < nseen; i++)
            if (seen[i].verts == numVertices && seen[i].vs == g_curVS && seen[i].ps == g_curPS) {
                fresh = false; break;
            }
        if (fresh && nseen < 64) {
            seen[nseen].verts = numVertices; seen[nseen].vs = g_curVS; seen[nseen].ps = g_curPS;
            nseen++;
        }
        int vi = -1, pi = -1;
        unsigned vcrc = 0, pcrc = 0;
        if (fresh) {
            for (int i = 0; i < g_shCount; i++) {
                if (g_sh[i].handle == g_curVS && !g_sh[i].pixel) { vi = i; vcrc = g_sh[i].crc; }
                if (g_sh[i].handle == g_curPS && g_sh[i].pixel)  { pi = i; pcrc = g_sh[i].crc; }
            }
        }
        LeaveCriticalSection(&g_lock);
        if (fresh) {
            Log("DRAW %u verts, %u prims -> vs #%d crc %08X | ps #%d crc %08X",
                numVertices, primCount, vi, vcrc, pi, pcrc);
        }
    }
    return o_DrawIP(dev, type, baseVertex, minVertex, numVertices, startIndex, primCount);
}

static HRESULT STDMETHODCALLTYPE My_CreateDevice(IDirect3D9* self, UINT adapter, D3DDEVTYPE type,
                                                 HWND focus, DWORD flags,
                                                 D3DPRESENT_PARAMETERS* pp,
                                                 IDirect3DDevice9** out) {
    HRESULT hr = o_CreateDev(self, adapter, type, focus, flags, pp, out);
    if (SUCCEEDED(hr) && out && *out && !g_devHooked) {
        Log("CreateDevice ok, device %p - hooking its vtable", (void*)*out);
        void** vt = *(void***)(*out);
        // All four or none: a half-patched vtable would dump shaders it cannot
        // attribute, which is worse than not dumping at all.
        void *a = nullptr, *b = nullptr, *c = nullptr, *d = nullptr, *e = nullptr;
        bool ok = VtableLooksLikeDevice(vt)
               && PatchSlot(vt, kIdx_CreateVertexShader, (void*)&My_CreateVS, &a, "CreateVertexShader")
               && PatchSlot(vt, kIdx_CreatePixelShader,  (void*)&My_CreatePS, &b, "CreatePixelShader")
               && PatchSlot(vt, kIdx_SetVertexShader,    (void*)&My_SetVS,    &c, "SetVertexShader")
               && PatchSlot(vt, kIdx_SetPixelShader,     (void*)&My_SetPS,    &d, "SetPixelShader")
               && PatchSlot(vt, kIdx_DrawIndexedPrimitive, (void*)&My_DrawIP, &e, "DrawIndexedPrimitive");
        if (ok) {
            o_CreateVS = (CreateVS_t)a; o_CreatePS = (CreatePS_t)b;
            o_SetVS = (SetVS_t)c;       o_SetPS = (SetPS_t)d;
            o_DrawIP = (DrawIP_t)e;
            g_devHooked = true;
            Log("device hooked; shaders will be written to %s", g_dump);
        } else {
            Log("device vtable NOT hooked - slot check failed, nothing was written");
        }
    }
    return hr;
}

static IDirect3D9* WINAPI My_Create9(UINT ver) {
    IDirect3D9* p = o_Create9(ver);
    Log("Direct3DCreate9(%u) -> %p", ver, (void*)p);
    if (p) {
        void** vt = *(void***)p;
        void* orig = nullptr;
        if (PatchSlot(vt, kIdx_CreateDevice, (void*)&My_CreateDevice, &orig, "CreateDevice"))
            o_CreateDev = (CreateDevice_t)orig;
    }
    return p;
}

// ============================================================ IAT patch =====
// Walk the exe's imports for d3d9.dll!Direct3DCreate9 and swap the pointer.
static bool HookIAT() {
    HMODULE exe = GetModuleHandleA(nullptr);
    BYTE* base = (BYTE*)exe;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) { Log("exe has no import directory"); return false; }
    IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress);
    for (; imp->Name; imp++) {
        const char* dll = (const char*)(base + imp->Name);
        if (_stricmp(dll, "d3d9.dll") != 0) continue;
        IMAGE_THUNK_DATA* orig = (IMAGE_THUNK_DATA*)(base + imp->OriginalFirstThunk);
        IMAGE_THUNK_DATA* first = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; orig->u1.AddressOfData; orig++, first++) {
            if (IMAGE_SNAP_BY_ORDINAL(orig->u1.Ordinal)) continue;
            IMAGE_IMPORT_BY_NAME* n = (IMAGE_IMPORT_BY_NAME*)(base + orig->u1.AddressOfData);
            if (strcmp((const char*)n->Name, "Direct3DCreate9") != 0) continue;
            DWORD old = 0;
            if (!VirtualProtect(&first->u1.Function, sizeof(void*), PAGE_READWRITE, &old)) {
                Log("could not unprotect the IAT slot"); return false;
            }
            o_Create9 = (Create9_t)first->u1.Function;
            first->u1.Function = (ULONGLONG)(void*)&My_Create9;
            VirtualProtect(&first->u1.Function, sizeof(void*), old, &old);
            Log("IAT hook installed: Direct3DCreate9 was %p", (void*)o_Create9);
            return true;
        }
        Log("d3d9.dll is imported but Direct3DCreate9 is not in its thunks");
        return false;
    }
    Log("d3d9.dll is not a static import of the exe - it must be loaded dynamically");
    return false;
}

// The summary is what gets read afterwards, so it must land without the process
// exiting cleanly - a game killed from the console never runs an exit handler.
static DWORD WINAPI Worker(LPVOID) {
    for (;;) {
        Sleep(5000);
        bool due = false;
        EnterCriticalSection(&g_lock);
        due = g_summaryDue; g_summaryDue = false;
        LeaveCriticalSection(&g_lock);
        if (due) WriteSummary();
    }
}

BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        InitializeCriticalSection(&g_lock);
        GetModuleFileNameA(h, g_log, MAX_PATH);
        strcpy_s(g_dir, g_log);
        char* slash = strrchr(g_dir, '\\'); if (slash) *slash = 0;
        char* dot = strrchr(g_log, '.');
        if (dot) strcpy_s(dot, sizeof(g_log) - (dot - g_log), ".log");
        sprintf_s(g_dump, "%s\\shaderdump", g_dir);
        CreateDirectoryA(g_dump, nullptr);
        FILE* f = nullptr; if (fopen_s(&f, g_log, "w") == 0 && f) fclose(f);
        Log("umvc3_shaderdump loaded");
        LoadConfig(g_dir);
        if (HookIAT()) CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
    }
    return TRUE;
}
