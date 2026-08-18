<#
    Window control for the Steam/LUCA build during engine verification.

    game_steam.ps1 -Action launch [-Wait 30]
    game_steam.ps1 -Action resume [-Out path.png]
    game_steam.ps1 -Action shot [-Out path.png] [-Full]
    game_steam.ps1 -Action opening [-Out path-prefix] [-Frames 50] [-Interval 600]
    game_steam.ps1 -Action click -X 960 -Y 540
    game_steam.ps1 -Action key -Key ENTER
    game_steam.ps1 -Action keydown -Key LCTRL
    game_steam.ps1 -Action keyup -Key LCTRL
    game_steam.ps1 -Action info
    game_steam.ps1 -Action state
    game_steam.ps1 -Action exit
    game_steam.ps1 -Action close
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('launch', 'resume', 'opening', 'shot', 'click', 'key', 'keydown', 'keyup', 'state', 'info', 'exit', 'close')]
    [string]$Action,
    [int]$Wait = 30,
    [string]$Out,
    [int]$X,
    [int]$Y,
    [string]$Key,
    [int]$Frames = 50,
    [int]$Interval = 600,
    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
while (-not (Test-Path (Join-Path $Root 'AGENTS.md'))) {
    $parent = Split-Path -Parent $Root
    if ($parent -eq $Root -or -not $parent) { throw "Repository root not found" }
    $Root = $parent
}

$GameDir = Join-Path $Root 'Summer Pockets REFLECTION BLUE_Steam'
$GameExe = Join-Path $GameDir 'SummerPocketsRB.exe'
$ShotDir = Join-Path $PSScriptRoot 'shots-steam'

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

if (-not ([System.Management.Automation.PSTypeName]'SteamGameWin32').Type) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SteamGameWin32 {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
}
[void][SteamGameWin32]::SetProcessDPIAware()

$KeyCodes = @{
    LCTRL = 0xA2
    CTRL = 0xA2
    ENTER = 0x0D
    ESC = 0x1B
    SPACE = 0x20
    F1 = 0x70
}

function Get-GameProcess {
    Get-Process -Name 'SummerPocketsRB' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
}

function Get-GameWindow {
    $process = Get-GameProcess
    if (-not $process) { throw 'Game is not running or its window is not ready' }
    $process.MainWindowHandle
}

function Get-ClientArea($hwnd) {
    $rect = New-Object SteamGameWin32+RECT
    [void][SteamGameWin32]::GetClientRect($hwnd, [ref]$rect)
    $point = New-Object SteamGameWin32+POINT
    $point.X = 0
    $point.Y = 0
    [void][SteamGameWin32]::ClientToScreen($hwnd, [ref]$point)
    [pscustomobject]@{
        X = $point.X
        Y = $point.Y
        Width = $rect.Right - $rect.Left
        Height = $rect.Bottom - $rect.Top
    }
}

function Set-GameFocus($hwnd) {
    [void][SteamGameWin32]::ShowWindow($hwnd, 9)
    [void][SteamGameWin32]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 250
}

function Start-Game([int]$waitSeconds) {
    $existing = Get-GameProcess
    if ($existing) { return $existing.MainWindowHandle }
    Start-Process -FilePath $GameExe -WorkingDirectory $GameDir | Out-Null
    for ($i = 0; $i -lt ($waitSeconds * 4); $i++) {
        Start-Sleep -Milliseconds 250
        $process = Get-GameProcess
        if ($process) {
            Start-Sleep -Milliseconds 1000
            return $process.MainWindowHandle
        }
    }
    throw 'Game window did not appear'
}

function Save-Shot($hwnd, [string]$path, [switch]$FullScreen) {
    Set-GameFocus $hwnd
    if ($FullScreen) {
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $originX = $bounds.X
        $originY = $bounds.Y
        $width = $bounds.Width
        $height = $bounds.Height
    }
    else {
        $area = Get-ClientArea $hwnd
        $originX = $area.X
        $originY = $area.Y
        $width = $area.Width
        $height = $area.Height
    }
    if (-not $path) {
        $path = Join-Path $ShotDir ('shot_{0}.png' -f (Get-Date -Format 'HHmmss'))
    }
    $directory = Split-Path -Parent $path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($originX, $originY, 0, 0, (New-Object System.Drawing.Size($width, $height)))
    $graphics.Dispose()
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    $path
}

function Get-GamePixel($hwnd, [int]$x, [int]$y) {
    $area = Get-ClientArea $hwnd
    $bitmap = New-Object System.Drawing.Bitmap(1, 1)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen(($area.X + $x), ($area.Y + $y), 0, 0, (New-Object System.Drawing.Size(1, 1)))
    $graphics.Dispose()
    $color = $bitmap.GetPixel(0, 0)
    $bitmap.Dispose()
    $color
}

function Test-NearWhite($color) {
    $color.R -ge 245 -and $color.G -ge 245 -and $color.B -ge 245
}

function Get-ScreenState($hwnd) {
    $start = Get-GamePixel $hwnd 330 365
    $titleBackground = Get-GamePixel $hwnd 100 700
    if ((Test-NearWhite $start) -and -not (Test-NearWhite $titleBackground)) {
        return 'title'
    }
    $slot = Get-GamePixel $hwnd 300 330
    if ($slot.R -lt 100 -and $slot.G -lt 140 -and $slot.B -lt 190) {
        return 'load'
    }
    $gear = Get-GamePixel $hwnd 1765 868
    if (Test-NearWhite $gear) { return 'game' }
    'other'
}

function Invoke-ClientClick($hwnd, [int]$x, [int]$y) {
    Set-GameFocus $hwnd
    $area = Get-ClientArea $hwnd
    [void][SteamGameWin32]::SetCursorPos(($area.X + $x), ($area.Y + $y))
    Start-Sleep -Milliseconds 80
    [SteamGameWin32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [SteamGameWin32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
}

function Wait-ScreenState($hwnd, [string]$wanted, [int]$tries = 30) {
    for ($i = 0; $i -lt $tries; $i++) {
        if ((Get-ScreenState $hwnd) -eq $wanted) { return $true }
        Start-Sleep -Milliseconds 300
    }
    $false
}

function Send-KeyEvent([string]$name, [bool]$release) {
    $upper = $name.ToUpperInvariant()
    if (-not $KeyCodes.ContainsKey($upper)) { throw "Unsupported key: $name" }
    $flags = if ($release) { 0x0002 } else { 0 }
    [SteamGameWin32]::keybd_event([byte]$KeyCodes[$upper], 0, $flags, [UIntPtr]::Zero)
}

switch ($Action) {
    'launch' {
        $hwnd = Start-Game $Wait
        $area = Get-ClientArea $hwnd
        $process = Get-GameProcess
        "PID $($process.Id), client $($area.Width)x$($area.Height) at ($($area.X),$($area.Y))"
    }
    'info' {
        $process = Get-GameProcess
        if (-not $process) { 'Game is not running'; break }
        $area = Get-ClientArea $process.MainWindowHandle
        "PID $($process.Id), hwnd $($process.MainWindowHandle), client $($area.Width)x$($area.Height) at ($($area.X),$($area.Y))"
    }
    'state' {
        Get-ScreenState (Get-GameWindow)
    }
    'resume' {
        $hwnd = Start-Game $Wait
        Set-GameFocus $hwnd
        for ($i = 0; $i -lt 45; $i++) {
            if ((Get-ScreenState $hwnd) -eq 'title') { break }
            Invoke-ClientClick $hwnd 960 1000
            Start-Sleep -Milliseconds 500
        }
        if ((Get-ScreenState $hwnd) -ne 'title') { throw 'Title screen did not appear' }
        Invoke-ClientClick $hwnd 615 365
        if (-not (Wait-ScreenState $hwnd 'load' 30)) { throw 'Load screen did not appear' }
        Invoke-ClientClick $hwnd 300 330
        Start-Sleep -Milliseconds 500
        Invoke-ClientClick $hwnd 805 575
        if (-not (Wait-ScreenState $hwnd 'game' 40)) { throw 'Saved scene did not load' }
        Start-Sleep -Milliseconds 700
        Save-Shot $hwnd $Out
    }
    'opening' {
        $hwnd = Start-Game $Wait
        Set-GameFocus $hwnd
        for ($i = 0; $i -lt 45; $i++) {
            if ((Get-ScreenState $hwnd) -eq 'title') { break }
            Invoke-ClientClick $hwnd 960 1000
            Start-Sleep -Milliseconds 500
        }
        if ((Get-ScreenState $hwnd) -ne 'title') { throw 'Title screen did not appear' }
        if (-not $Out) { $Out = Join-Path $ShotDir 'opening-preview' }
        Invoke-ClientClick $hwnd 330 365
        for ($i = 0; $i -lt $Frames; $i++) {
            Start-Sleep -Milliseconds $Interval
            $path = '{0}-{1:D3}.png' -f $Out, $i
            Save-Shot $hwnd $path | Out-Null
        }
        "Captured $Frames opening frames with prefix $Out"
    }
    'shot' {
        Save-Shot (Get-GameWindow) $Out -FullScreen:$Full
    }
    'click' {
        $hwnd = Get-GameWindow
        Invoke-ClientClick $hwnd $X $Y
        "Clicked ($X,$Y)"
    }
    'key' {
        $hwnd = Get-GameWindow
        Set-GameFocus $hwnd
        Send-KeyEvent $Key $false
        Start-Sleep -Milliseconds 60
        Send-KeyEvent $Key $true
        "Pressed $Key"
    }
    'keydown' {
        $hwnd = Get-GameWindow
        Set-GameFocus $hwnd
        Send-KeyEvent $Key $false
        "Key down: $Key"
    }
    'keyup' {
        Send-KeyEvent $Key $true
        "Key up: $Key"
    }
    'exit' {
        $process = Get-GameProcess
        if (-not $process) { 'Game is not running'; break }
        $hwnd = $process.MainWindowHandle
        $state = Get-ScreenState $hwnd
        if ($state -eq 'load') {
            Invoke-ClientClick $hwnd 1810 1045
            Start-Sleep -Milliseconds 500
            $state = Get-ScreenState $hwnd
        }
        if ($state -eq 'title') {
            Invoke-ClientClick $hwnd 1600 365
            Start-Sleep -Milliseconds 500
            Invoke-ClientClick $hwnd 805 575
        }
        else {
            Invoke-ClientClick $hwnd 1765 868
            Start-Sleep -Milliseconds 500
            Invoke-ClientClick $hwnd 1440 700
            Start-Sleep -Milliseconds 500
            Invoke-ClientClick $hwnd 805 605
        }
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) { break }
        }
        if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
            throw 'Game did not exit through its UI'
        }
        'Game exited through its UI'
    }
    'close' {
        $process = Get-GameProcess
        if (-not $process) { 'Game is not running'; break }
        [void]$process.CloseMainWindow()
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) { break }
        }
        if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
            'Close requested; game is still running'
        }
        else {
            'Game closed'
        }
    }
}
