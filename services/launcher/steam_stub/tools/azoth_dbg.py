#!/usr/bin/env python3
"""Minimal Windows debugger for Azoth stub crashes (stdlib ctypes only).

Launches Bin64\\NewWorld.exe under DEBUG_PROCESS, waits for the first
0xC0000005, then dumps: fault RIP, fault address, registers, module bases
and a raw return-address stack walk. No admin, no installs.

Usage:
  python tools/azoth_dbg.py [--timeout 90] [--log PATH]
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

DEBUG_PROCESS = 0x1
DEBUG_ONLY_THIS_PROCESS = 0x2
INFINITE = 0xFFFFFFFF
EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_THREAD_DEBUG_EVENT = 4
EXIT_PROCESS_DEBUG_EVENT = 5
LOAD_DLL_DEBUG_EVENT = 6
EXCEPTION_ACCESS_VIOLATION = 0xC0000005
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
CONTEXT_FULL = 0x10000B


class STARTUPINFO(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
                ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
                ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
                ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
                ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
                ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [('ExceptionCode', wintypes.DWORD), ('ExceptionFlags', wintypes.DWORD),
                ('ExceptionRecord', ctypes.c_void_p), ('ExceptionAddress', ctypes.c_void_p),
                ('NumberParameters', wintypes.DWORD),
                ('ExceptionInformation', ctypes.c_ulonglong * 15)]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('ExceptionRecord', EXCEPTION_RECORD), ('dwFirstChance', wintypes.DWORD)]


class CREATE_PROCESS_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('hFile', wintypes.HANDLE), ('hProcess', wintypes.HANDLE),
                ('hThread', wintypes.HANDLE), ('lpBaseOfImage', ctypes.c_void_p),
                ('dwDebugInfoFileOffset', wintypes.DWORD), ('nDebugInfoSize', wintypes.DWORD),
                ('lpThreadLocalBase', ctypes.c_void_p),
                ('lpStartAddress', ctypes.c_void_p), ('lpImageName', ctypes.c_void_p),
                ('fUnicode', wintypes.WORD)]


class LOAD_DLL_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('hFile', wintypes.HANDLE), ('lpBaseOfDll', ctypes.c_void_p),
                ('dwDebugInfoFileOffset', wintypes.DWORD), ('nDebugInfoSize', wintypes.DWORD),
                ('lpImageName', ctypes.c_void_p), ('fUnicode', wintypes.WORD)]


class CREATE_THREAD_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('hThread', wintypes.HANDLE), ('lpThreadLocalBase', ctypes.c_void_p),
                ('lpStartAddress', ctypes.c_void_p)]


class _U(ctypes.Union):
    _fields_ = [('Exception', EXCEPTION_DEBUG_INFO),
                ('CreateThread', CREATE_THREAD_DEBUG_INFO),
                ('CreateProcessInfo', CREATE_PROCESS_DEBUG_INFO),
                ('LoadDll', LOAD_DLL_DEBUG_INFO),
                ('ExitCode', wintypes.DWORD),
                ('raw', ctypes.c_byte * 160)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [('dwDebugEventCode', wintypes.DWORD), ('dwProcessId', wintypes.DWORD),
                ('dwThreadId', wintypes.DWORD), ('u', _U)]


class CONTEXT(ctypes.Structure):
    _fields_ = [('P1Home', ctypes.c_ulonglong), ('P2Home', ctypes.c_ulonglong),
                ('P3Home', ctypes.c_ulonglong), ('P4Home', ctypes.c_ulonglong),
                ('P5Home', ctypes.c_ulonglong), ('P6Home', ctypes.c_ulonglong),
                ('ContextFlags', wintypes.DWORD), ('MxCsr', wintypes.DWORD),
                ('SegCs', wintypes.WORD), ('SegDs', wintypes.WORD),
                ('SegEs', wintypes.WORD), ('SegFs', wintypes.WORD),
                ('SegGs', wintypes.WORD), ('SegSs', wintypes.WORD),
                ('EFlags', wintypes.DWORD), ('Dr0', ctypes.c_ulonglong),
                ('Dr1', ctypes.c_ulonglong), ('Dr2', ctypes.c_ulonglong),
                ('Dr3', ctypes.c_ulonglong), ('Dr6', ctypes.c_ulonglong),
                ('Dr7', ctypes.c_ulonglong), ('Rax', ctypes.c_ulonglong),
                ('Rcx', ctypes.c_ulonglong), ('Rdx', ctypes.c_ulonglong),
                ('Rbx', ctypes.c_ulonglong), ('Rsp', ctypes.c_ulonglong),
                ('Rbp', ctypes.c_ulonglong), ('Rsi', ctypes.c_ulonglong),
                ('Rdi', ctypes.c_ulonglong), ('R8', ctypes.c_ulonglong),
                ('R9', ctypes.c_ulonglong), ('R10', ctypes.c_ulonglong),
                ('R11', ctypes.c_ulonglong), ('R12', ctypes.c_ulonglong),
                ('R13', ctypes.c_ulonglong), ('R14', ctypes.c_ulonglong),
                ('R15', ctypes.c_ulonglong), ('Rip', ctypes.c_ulonglong)]


def read_mem(hproc, addr, size):
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t()
    if k32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)):
        return buf.raw[:n.value]
    return b''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeout', type=float, default=90)
    ap.add_argument('--log', type=Path, default=Path(os.environ.get('TEMP', '.')) / 'azoth_dbg.log')
    ns = ap.parse_args()
    rt = Path(os.environ['LOCALAPPDATA']) / 'Azoth' / 'game' / 'Bin64'
    exe = rt / 'NewWorld.exe'
    if not exe.exists():
        print(f'missing {exe} (run Start-NwPrivate.ps1 first)');
        return 2

    si = STARTUPINFO();
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    os.environ['AZOTH_STUB_LOG'] = '1'
    ok = k32.CreateProcessW(str(exe), None, None, None, False,
                            DEBUG_PROCESS | DEBUG_ONLY_THIS_PROCESS, None,
                            str(rt), ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        print('CreateProcess failed', ctypes.get_last_error());
        return 2

    out = [f'exe={exe}', f'pid={pi.dwProcessId}']
    print('\n'.join(out))
    modules: dict[int, str] = {}
    base_main = 0
    threads: dict[int, int] = {}
    t0 = time.time()
    crashed = False
    try:
        while time.time() - t0 < ns.timeout:
            ev = DEBUG_EVENT()
            if not k32.WaitForDebugEvent(ctypes.byref(ev), 500):
                continue
            code = ev.dwDebugEventCode
            status = DBG_CONTINUE
            if code == CREATE_PROCESS_DEBUG_EVENT:
                base_main = ev.u.CreateProcessInfo.lpBaseOfImage or 0
                threads[ev.dwThreadId] = ev.u.CreateProcessInfo.hThread
                out.append(f'main_base={base_main:#x}')
            elif code == CREATE_THREAD_DEBUG_EVENT:
                threads[ev.dwThreadId] = ev.u.CreateThread.hThread
            elif code == EXIT_THREAD_DEBUG_EVENT:
                h = threads.pop(ev.dwThreadId, None)
                if h:
                    k32.CloseHandle(h)
            elif code == LOAD_DLL_DEBUG_EVENT:
                dll_base = ev.u.LoadDll.lpBaseOfDll or 0
                hfile = ev.u.LoadDll.hFile
                name = f'dll@{dll_base:#x}'
                if hfile:
                    n = ctypes.create_unicode_buffer(512)
                    if k32.GetFinalPathNameByHandleW(hfile, n, 512, 0):
                        name = f'{Path(n.value).name}@{dll_base:#x}'
                    k32.CloseHandle(hfile)
                modules[dll_base] = name
            elif code == EXCEPTION_DEBUG_EVENT:
                rec = ev.u.Exception.ExceptionRecord
                if rec.ExceptionCode == EXCEPTION_ACCESS_VIOLATION and ev.u.Exception.dwFirstChance:
                    crashed = True
                    rip = rec.ExceptionAddress or 0
                    rw = rec.ExceptionInformation[0] if rec.NumberParameters > 0 else 0
                    fault = rec.ExceptionInformation[1] if rec.NumberParameters > 1 else 0
                    hth = threads.get(ev.dwThreadId)
                    regs = {}
                    if hth:
                        cx = CONTEXT();
                        cx.ContextFlags = CONTEXT_FULL
                        if k32.GetThreadContext(hth, ctypes.byref(cx)):
                            regs = {r: getattr(cx, r) for r in
                                    'Rax Rcx Rdx Rbx Rsp Rbp Rsi Rdi R8 R9 R10 R11 R12 R13 R14 R15 Rip'.split()}
                            rip = regs['Rip']
                    owner = 'unknown'
                    for b, nm in sorted(modules.items(), reverse=True):
                        if isinstance(b, int) and rip >= b:
                            owner = f'{nm}+{rip - b:#x}'
                            break
                    if base_main and base_main <= rip:
                        owner = f'NewWorld.exe+{rip - base_main:#x}'
                    out.append(f'AV first-chance rip={rip:#x} ({owner}) rw={rw} fault={fault:#x}')
                    for r, v in regs.items():
                        out.append(f'  {r}={v:#018x}')
                    # raw stack return addresses
                    if regs:
                        raw = read_mem(pi.hProcess, regs['Rsp'], 8 * 40)
                        out.append('stack:')
                        for i in range(0, len(raw) - 7, 8):
                            a = int.from_bytes(raw[i:i + 8], 'little')
                            if base_main and base_main < a < base_main + 0x20000000:
                                out.append(f'  rsp+{i:#x}: NewWorld.exe+{a - base_main:#x}')
                            else:
                                for b, nm in modules.items():
                                    if isinstance(b, int) and b < a < b + 0x1000000:
                                        out.append(f'  rsp+{i:#x}: {nm}+{a - b:#x}')
                                        break
                    status = DBG_EXCEPTION_NOT_HANDLED
                    k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, status)
                    break
                status = DBG_EXCEPTION_NOT_HANDLED
            elif code == EXIT_PROCESS_DEBUG_EVENT and ev.dwProcessId == pi.dwProcessId:
                out.append(f'process exited cleanly (no AV) code={ev.u.ExitCode}')
                k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
                break
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, status)
        else:
            out.append('TIMEOUT: still alive, no AV seen')
    finally:
        ns.log.write_text('\n'.join(out) + '\n', encoding='utf-8')
        print('\n'.join(o for o in out if o.startswith(('AV', 'process', 'TIMEOUT', 'stack', '  '))))
        print(f'full log: {ns.log}')
        if crashed:
            try:
                k32.TerminateProcess(pi.hProcess, 1)
            except OSError:
                pass
        else:
            # Leave the game running: detach instead of killing.
            try:
                k32.DebugActiveProcessStop(pi.dwProcessId)
            except OSError:
                pass
    return 0 if crashed else 1


if __name__ == '__main__':
    sys.exit(main())
