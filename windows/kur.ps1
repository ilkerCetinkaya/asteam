<#
  Renk Ölçüm Bulut Köprüsü — Windows kurulumu
  Köprüyü, kullanıcı Windows'a giriş yaptığında arka planda (pencere açmadan) başlatan
  bir Zamanlanmış Görev oluşturur. Çökerse 1 dakika sonra yeniden başlar.

  Kullanım (PowerShell):
    .\kur.ps1 -Klasor "C:\ProgramVerisi\Olcumler" -Esleme "C:\RenkOlcum\esleme.json"
  Kaldırmak için:
    .\kur.ps1 -Kaldir
#>
param(
  [string]$Klasor,
  [string]$Esleme = "$PSScriptRoot\esleme.json",
  [string]$Desen = "*.mdb",
  [string]$Exe = "$PSScriptRoot\renkolcum-kopru.exe",
  [switch]$Kaldir
)
$Gorev = "RenkOlcum Bulut Koprusu"
if ($Kaldir) {
  Unregister-ScheduledTask -TaskName $Gorev -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Görev kaldırıldı."
  exit 0
}
if (-not $Klasor) { throw "-Klasor parametresi gerekli (uygulamanın .mdb dosyalarını yazdığı klasör)" }
if (-not (Test-Path $Exe)) { throw "Bulunamadı: $Exe" }
if (-not (Test-Path $Esleme)) { throw "Bulunamadı: $Esleme  (önce: renkolcum.exe mdb-kesfet <dosya.mdb> --yaz esleme.json)" }

$arg = "mdb-izle `"$Klasor`" --esleme `"$Esleme`" --desen `"$Desen`" --sessiz"
$action   = New-ScheduledTaskAction -Execute $Exe -Argument $arg -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Gorev -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $Gorev
Write-Host "Kuruldu ve başlatıldı: $Gorev"
Write-Host "Günlük dosyası: $env:USERPROFILE\.renkolcum\kopru.log"
