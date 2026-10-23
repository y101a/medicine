#Requires -RunAsAdministrator
param([Parameter(Mandatory = $true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'

# Read-only host diagnostics. Does not enable features, edit BCD, install WSL,
# restart Windows, or change permissions. Refuses to overwrite output.
$perfOutput = [System.IO.Path]::GetFullPath($OutputPath)
$perfFeatures = foreach ($feature in @(
    'VirtualMachinePlatform',
    'Microsoft-Windows-Subsystem-Linux',
    'Microsoft-Hyper-V-Hypervisor'
)) {
    try {
        $value = Get-WindowsOptionalFeature -Online -FeatureName $feature
        @{ name = $feature; state = [string]$value.State }
    } catch {
        @{ name = $feature; error = $_.Exception.Message }
    }
}
$perfReport = @{
    collectedAt = (Get-Date).ToString('o')
    hypervisorPresent = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
    processors = @(Get-CimInstance Win32_Processor | Select-Object Name,
        VirtualizationFirmwareEnabled, VMMonitorModeExtensions)
    features = @($perfFeatures)
    bootConfiguration = @(& "$env:WINDIR\System32\bcdedit.exe" /enum 2>&1 |
        ForEach-Object { [string]$_ })
}
$perfStream = [System.IO.File]::Open($perfOutput, [System.IO.FileMode]::CreateNew)
$perfWriter = [System.IO.StreamWriter]::new($perfStream, [System.Text.UTF8Encoding]::new($false))
try {
    $perfWriter.Write(($perfReport | ConvertTo-Json -Depth 6))
} finally {
    $perfWriter.Dispose()
}
