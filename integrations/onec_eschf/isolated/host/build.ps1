param([Parameter(Mandatory=$true)][string]$NewOutputDirectory)
$ErrorActionPreference = 'Stop'
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$expectedCompiler = '46809206887326d2d24db1eff1f3064de972c3451abe766b49111450a5e08e00'
$framework = Split-Path -Parent $compiler
$source = Join-Path $PSScriptRoot 'FixedComHost.cs'
$hash = {param($path) (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
if ((& $hash $compiler) -cne $expectedCompiler) { throw 'Compiler changed; review required' }
$output = [IO.Path]::GetFullPath($NewOutputDirectory)
$parent = Get-Item -LiteralPath (Split-Path -Parent $output)
if ((Test-Path -LiteralPath $output) -or $output -match '["\r\n]' -or
    ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'New local output required' }
$references = @('mscorlib.dll','System.dll','System.Core.dll','System.Web.Extensions.dll')
$referenceFacts = @()
$arguments = @('/nologo','/target:exe','/platform:x64','/langversion:5','/optimize+','/debug-',
    '/noconfig','/nostdlib+','/warn:4')
foreach ($name in $references) {
    $path = Join-Path $framework $name
    $referenceFacts += [ordered]@{path=$path; sha256=(& $hash $path); file_version=(Get-Item -LiteralPath $path).VersionInfo.FileVersion}
    $arguments += '/reference:' + $path
}
[void][IO.Directory]::CreateDirectory($output)
$report = [ordered]@{schema_version=1; scope='local_build_only'; native_com_invoked=$false;
    nt63_runtime_verified=$false; deterministic_binary_claim=$false; compiler_path=$compiler;
    compiler_sha256=(& $hash $compiler); compiler_version=(Get-Item -LiteralPath $compiler).VersionInfo.FileVersion;
    source_path=$source; source_sha256=(& $hash $source); build_script_sha256=(& $hash $PSCommandPath);
    references=$referenceFacts; outputs=@(); completed=$false}
foreach ($backend in @('production','synthetic')) {
    $filename = if ($backend -eq 'production') {'eschf-probe.exe'} else {'eschf-probe-synthetic.exe'}
    $destination = Join-Path $output $filename
    $invocation = @($arguments) + @('/out:' + $destination)
    if ($backend -eq 'synthetic') { $invocation += '/define:SYNTHETIC_BACKEND' }
    $invocation += $source
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $compilerOutput = @(& $compiler @invocation 2>&1)
    $exitCode = $LASTEXITCODE; $watch.Stop()
    if ($exitCode -ne 0) { $compilerOutput | Write-Output; throw ('Compiler failed: ' + $backend) }
    $report.outputs += [ordered]@{backend=$backend; file=$filename; sha256=(& $hash $destination);
        length=(Get-Item -LiteralPath $destination).Length; elapsed_ms=$watch.ElapsedMilliseconds;
        arguments=$invocation; compiler_messages=@($compilerOutput | ForEach-Object {[string]$_})}
}
$report.completed = $true
$receipt = Join-Path $output 'build-provenance.json'
[IO.File]::WriteAllText($receipt, ($report | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
[pscustomobject]@{receipt=$receipt; production_sha256=$report.outputs[0].sha256;
    synthetic_sha256=$report.outputs[1].sha256; nt63_runtime_verified=$false} | ConvertTo-Json -Compress
