<#
    Управление игрой для отладки перевода.

    game.ps1 -Action launch [-Wait 15]
    game.ps1 -Action resume [-Out кадр.png]   запуск + меню + загрузка первого сейва
    game.ps1 -Action shot   [-Out кадр.png] [-Full]
    game.ps1 -Action click  -X 100 -Y 200
    game.ps1 -Action key    -Key ENTER
    game.ps1 -Action state                    что сейчас на экране
    game.ps1 -Action info
    game.ps1 -Action close                    выход с подтверждением
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('launch', 'resume', 'shot', 'click', 'key', 'state', 'info', 'close')]
    [string]$Action,
    [int]$Wait = 15,
    [string]$Out,
    [int]$X,
    [int]$Y,
    [string]$Key,
    [switch]$Full
)

$ErrorActionPreference = 'Stop'

# Корень ищется по AGENTS.md вверх от скрипта, как в game-tools/paths.py,
# чтобы репозиторий можно было держать где угодно.
$Root = Split-Path -Parent $PSScriptRoot
while (-not (Test-Path (Join-Path $Root 'AGENTS.md'))) {
    $parent = Split-Path -Parent $Root
    if ($parent -eq $Root -or -not $parent) { throw "Не найден корень репозитория (AGENTS.md) выше $PSScriptRoot" }
    $Root = $parent
}

# Значение дублирует game.install_dir из config/project.yaml.
$GameDir = Join-Path $Root 'Summer Pockets REFLECTION BLUE'
$GameExe = Join-Path $GameDir 'SiglusEngine.exe'
$ShotDir = Join-Path $PSScriptRoot 'shots'

# Опорные точки интерфейса в клиентских координатах (окно 1920x1080)
$UI = @{
    TitleLoad   = @(956, 364)
    TitleQuit   = @(1520, 364)
    Slot000     = @(220, 260)
    ConfirmYes  = @(886, 564)
    InGameQuit  = @(1196, 1046)
    Dismiss     = @(960, 900)     # безопасное место для кликов-пропусков
    ProbeTitle  = @(600, 248)     # белый, когда показано титульное меню
    ProbeLoad   = @(960, 1035)    # белый, когда открыт экран LOAD
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

if (-not ([System.Management.Automation.PSTypeName]'Win32Api').Type) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Api {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
}
[void][Win32Api]::SetProcessDPIAware()

function Get-GameProcess {
    Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
}

function Get-GameWindow {
    $p = Get-GameProcess
    if (-not $p) { throw 'Игра не запущена или окно ещё не создано' }
    $p.MainWindowHandle
}

function Get-ClientArea($hwnd) {
    $rc = New-Object Win32Api+RECT
    [void][Win32Api]::GetClientRect($hwnd, [ref]$rc)
    $pt = New-Object Win32Api+POINT
    $pt.X = 0; $pt.Y = 0
    [void][Win32Api]::ClientToScreen($hwnd, [ref]$pt)
    [pscustomobject]@{
        X = $pt.X; Y = $pt.Y
        Width = $rc.Right - $rc.Left; Height = $rc.Bottom - $rc.Top
    }
}

function Set-GameFocus($hwnd) {
    [void][Win32Api]::ShowWindow($hwnd, 9)
    [void][Win32Api]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 250
}

function Invoke-GameClick($hwnd, [int]$cx, [int]$cy) {
    $a = Get-ClientArea $hwnd
    [void][Win32Api]::SetCursorPos(($a.X + $cx), ($a.Y + $cy))
    Start-Sleep -Milliseconds 90
    [Win32Api]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [Win32Api]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 120
}

function Get-GamePixel($hwnd, [int]$cx, [int]$cy) {
    $a = Get-ClientArea $hwnd
    $bmp = New-Object System.Drawing.Bitmap(1, 1)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(($a.X + $cx), ($a.Y + $cy), 0, 0, (New-Object System.Drawing.Size(1, 1)))
    $g.Dispose()
    $c = $bmp.GetPixel(0, 0)
    $bmp.Dispose()
    $c
}

function Test-White($c) { $c.R -ge 245 -and $c.G -ge 245 -and $c.B -ge 245 }

function Get-ScreenState($hwnd) {
    if (Test-White (Get-GamePixel $hwnd $UI.ProbeLoad[0]  $UI.ProbeLoad[1]))  { return 'load' }
    if (Test-White (Get-GamePixel $hwnd $UI.ProbeTitle[0] $UI.ProbeTitle[1])) { return 'title' }
    'other'
}

function Wait-State($hwnd, [string]$want, [int]$tries = 25, [switch]$ClickWhileWaiting) {
    for ($i = 0; $i -lt $tries; $i++) {
        if ((Get-ScreenState $hwnd) -eq $want) { return $true }
        if ($ClickWhileWaiting) { Invoke-GameClick $hwnd $UI.Dismiss[0] $UI.Dismiss[1] }
        Start-Sleep -Milliseconds 350
    }
    $false
}

function Save-Shot($hwnd, [string]$path, [switch]$FullScreen) {
    Set-GameFocus $hwnd
    if ($FullScreen) {
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $ox = $b.X; $oy = $b.Y; $w = $b.Width; $h = $b.Height
    }
    else {
        $a = Get-ClientArea $hwnd
        $ox = $a.X; $oy = $a.Y; $w = $a.Width; $h = $a.Height
    }
    if (-not $path) { $path = Join-Path $ShotDir ('shot_{0}.png' -f (Get-Date -Format 'HHmmss')) }
    $dir = Split-Path -Parent $path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($ox, $oy, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $g.Dispose()
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    $path
}

function Start-Game([int]$waitSec) {
    if (Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue) {
        return (Get-GameWindow)
    }
    Start-Process -FilePath $GameExe -WorkingDirectory $GameDir | Out-Null
    for ($i = 0; $i -lt ($waitSec * 4); $i++) {
        Start-Sleep -Milliseconds 250
        $p = Get-GameProcess
        if ($p) { Start-Sleep -Milliseconds 800; return $p.MainWindowHandle }
    }
    throw 'Окно игры не появилось'
}

switch ($Action) {

    'launch' {
        $hwnd = Start-Game $Wait
        $a = Get-ClientArea $hwnd
        Write-Output "PID $((Get-GameProcess).Id), клиент $($a.Width)x$($a.Height) в ($($a.X),$($a.Y))"
    }

    'info' {
        $p = Get-GameProcess
        if (-not $p) { Write-Output 'Игра не запущена'; break }
        $a = Get-ClientArea $p.MainWindowHandle
        Write-Output "PID $($p.Id)  hwnd $($p.MainWindowHandle)  клиент $($a.Width)x$($a.Height) в ($($a.X),$($a.Y))"
    }

    'state' {
        $hwnd = Get-GameWindow
        Write-Output (Get-ScreenState $hwnd)
    }

    'resume' {
        $hwnd = Start-Game $Wait
        Set-GameFocus $hwnd

        if (-not (Wait-State $hwnd 'title' 40 -ClickWhileWaiting)) {
            throw 'Титульное меню не появилось'
        }
        Write-Output 'титульное меню'

        Invoke-GameClick $hwnd $UI.TitleLoad[0] $UI.TitleLoad[1]
        if (-not (Wait-State $hwnd 'load' 25)) { throw 'Экран LOAD не открылся' }
        Write-Output 'экран LOAD'

        Invoke-GameClick $hwnd $UI.Slot000[0] $UI.Slot000[1]
        Start-Sleep -Milliseconds 600
        Invoke-GameClick $hwnd $UI.ConfirmYes[0] $UI.ConfirmYes[1]

        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 300
            if ((Get-ScreenState $hwnd) -eq 'other') { break }
        }
        Start-Sleep -Milliseconds 1200
        Write-Output 'сейв загружен'
        Write-Output (Save-Shot $hwnd $Out)
    }

    'shot' {
        Write-Output (Save-Shot (Get-GameWindow) $Out -FullScreen:$Full)
    }

    'click' {
        $hwnd = Get-GameWindow
        Set-GameFocus $hwnd
        Invoke-GameClick $hwnd $X $Y
        Write-Output "клик по ($X,$Y)"
    }

    'key' {
        $hwnd = Get-GameWindow
        Set-GameFocus $hwnd
        [System.Windows.Forms.SendKeys]::SendWait("{$Key}")
        Write-Output "клавиша {$Key}"
    }

    'close' {
        if (-not (Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue)) {
            Write-Output 'Игра не запущена'; break
        }
        try {
            $hwnd = Get-GameWindow
            Set-GameFocus $hwnd
            $state = Get-ScreenState $hwnd
            if ($state -eq 'title') {
                Invoke-GameClick $hwnd $UI.TitleQuit[0] $UI.TitleQuit[1]
            }
            else {
                Invoke-GameClick $hwnd $UI.InGameQuit[0] $UI.InGameQuit[1]
            }
            Start-Sleep -Milliseconds 900
            Invoke-GameClick $hwnd $UI.ConfirmYes[0] $UI.ConfirmYes[1]
            Start-Sleep -Milliseconds 1500
            # выход из игры может вернуть на титул — там подтверждаем ещё раз
            if (Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue) {
                $hwnd = Get-GameWindow
                if ((Get-ScreenState $hwnd) -eq 'title') {
                    Invoke-GameClick $hwnd $UI.TitleQuit[0] $UI.TitleQuit[1]
                    Start-Sleep -Milliseconds 900
                    Invoke-GameClick $hwnd $UI.ConfirmYes[0] $UI.ConfirmYes[1]
                    Start-Sleep -Milliseconds 1500
                }
            }
        }
        catch { }

        for ($i = 0; $i -lt 12; $i++) {
            if (-not (Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 500
        }
        $p = Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue
        if ($p) {
            $p | ForEach-Object { $_.CloseMainWindow() | Out-Null }
            Start-Sleep -Seconds 2
            $p = Get-Process -Name 'SiglusEngine' -ErrorAction SilentlyContinue
            if ($p) { $p | Stop-Process -Force }
            Write-Output 'Игра закрыта принудительно'
        }
        else {
            Write-Output 'Игра закрыта штатно'
        }
    }
}
