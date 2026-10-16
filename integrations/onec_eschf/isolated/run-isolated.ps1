param(
    [string]$ApprovedP2Path,
    [string]$ApprovedP2Sha256,
    [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'
$StandRoot = 'D:\CRM-ESCHF-001-Isolated'
$Target = $StandRoot + '\ka_eschf_test'
$ModuleName = 'CRMЭСЧФИзолированныйТест'
$Marker = 'CRM-ESCHF-001/4a4204e1-bad8-4f37-854a-f0b1495f8b61'

function Read-BoundedJson([string]$Path, [string]$Sha256) {
    if ($Sha256 -cnotmatch '\A[0-9a-f]{64}\z') { throw 'expected_hash_required' }
    $file = Get-Item -LiteralPath $Path
    if ($file.PSIsContainer -or $file.Length -gt 65536 -or
        ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'receipt_file_guard' }
    # Hash and parse the same detached bytes, not two independent file reads.
    $raw = [IO.File]::ReadAllBytes($file.FullName)
    if ($raw.Length -gt 65536) { throw 'receipt_file_guard' }
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $actual = ([BitConverter]::ToString($algorithm.ComputeHash($raw))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
    if ($actual -cne $Sha256) { throw 'receipt_hash_guard' }
    $decoder = New-Object Text.UTF8Encoding($false, $true)
    $text = $decoder.GetString($raw)
    if ($text.StartsWith([string][char]0xFEFF, [StringComparison]::Ordinal)) { $text = $text.Substring(1) }
    return ($text | ConvertFrom-Json)
}

function Assert-StandPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -cne $Path -or $full -match '["\r\n]' -or
        -not $full.StartsWith($StandRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'stand_path_guard'
    }
    $cursor = $full
    while ($cursor -and $cursor.Length -ge $StandRoot.Length) {
        if ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'reparse_path_guard'
        }
        $cursor = Split-Path -Parent $cursor
    }
}

function Assert-Approval([string]$Path, [string]$Hash) {
    # Launcher checks only. The fixed EXE repeats full admission before native activation.
    $approval = Read-BoundedJson $Path $Hash
    if ($approval.kind -cne 'CRM-ESCHF-001/P2/fixed-host-context-probe-v1' -or
        $approval.target -cne $Target -or $approval.host -cne '1CSRV') { throw 'exact_p2_required' }
    if ($approval.worker_executable -cne ($StandRoot + '\runtime\eschf-probe.exe')) {
        throw 'fixed_host_path_required'
    }
    Assert-StandPath $approval.worker_executable
    if ((Get-FileHash -LiteralPath $approval.worker_executable -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        $approval.worker_executable_sha256) { throw 'fixed_host_hash_required' }
    return $approval
}
function Invoke-OwnedProcess([string]$Executable, [string]$Arguments, [string]$Directory,
    [int]$TimeoutSeconds = 60, [long]$MaxPrivateBytes = 3221225472, [long]$MaxOutputBytes = 1048576) {
    $owned = $null
    $result = [ordered]@{scope='isolated_context_probe_only'; Complete=$false; CleanupConfirmed=$false}
    try {
        $owned = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Directory 'stdout.log') `
            -RedirectStandardError (Join-Path $Directory 'stderr.log')
        # Retain the OS handle before waiting: PS5 Start-Process can otherwise lose ExitCode.
        [void]$owned.Handle
        $result.Pid = $owned.Id
        $result.StartedUtc = $owned.StartTime.ToUniversalTime().ToString('o')
        $watch = [Diagnostics.Stopwatch]::StartNew()
        while (-not $owned.WaitForExit(100)) {
            $owned.Refresh()
            if ($watch.Elapsed.TotalSeconds -gt $TimeoutSeconds) { throw 'owned_process_deadline' }
            if ($owned.PrivateMemorySize64 -gt $MaxPrivateBytes) { throw 'owned_memory_limit' }
            $files = @(Get-ChildItem -LiteralPath $Directory -File | Select-Object -First 9)
            if ($files.Count -gt 8 -or ($files | Measure-Object Length -Sum).Sum -gt $MaxOutputBytes) {
                throw 'owned_output_limit'
            }
        }
        $files = @(Get-ChildItem -LiteralPath $Directory -File | Select-Object -First 9)
        if ($files.Count -gt 8 -or ($files | Measure-Object Length -Sum).Sum -gt $MaxOutputBytes) {
            throw 'owned_output_limit'
        }
        $result.ExitCode = $owned.ExitCode
        $result.Complete = ($owned.ExitCode -eq 0)
    } catch { $result.Failure = $_.Exception.Message }
    finally {
        if ($null -ne $owned) {
            try {
                if (-not $owned.HasExited) { $owned.Kill(); [void]$owned.WaitForExit(5000) }
                $result.CleanupConfirmed = $owned.HasExited
            } catch { $result.CleanupConfirmed = $false }
        }
        $result.Complete = ($result.Complete -and $result.CleanupConfirmed)
    }
    return $result
}

if ($FunctionsOnly) { return } # Local test seam; never connects or launches anything by itself.

# No COM activation in PowerShell. No relocation of powershell.exe is assumed.
$approval = Assert-Approval $ApprovedP2Path $ApprovedP2Sha256
$evidenceRoot = $StandRoot + '\evidence'
Assert-StandPath $evidenceRoot
$directory = Join-Path $evidenceRoot ('wrapper-' + [Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $directory) { throw 'unique_wrapper_path_required' }
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')))
[void][IO.Directory]::CreateDirectory($directory, $acl)
$admissionPath = [IO.Path]::GetFullPath($ApprovedP2Path)
if ($admissionPath -match '["\r\n]' -or $ApprovedP2Sha256 -cnotmatch '\A[0-9a-f]{64}\z') { throw 'admission_arguments' }
$arguments = '--approved-p2 "' + $admissionPath + '" --approved-p2-sha256 ' + $ApprovedP2Sha256
$receipt = Invoke-OwnedProcess $approval.worker_executable $arguments $directory -TimeoutSeconds 75
$receipt.admission_sha256 = $ApprovedP2Sha256
$receipt.AC03 = $false
[IO.File]::WriteAllText((Join-Path $directory 'wrapper-receipt.json'), ($receipt | ConvertTo-Json -Compress),
    (New-Object Text.UTF8Encoding($false)))
if (-not $receipt.Complete) { throw 'fixed_host_failed_no_retry' }
