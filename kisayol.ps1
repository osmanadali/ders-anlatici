# Masaüstüne ve Başlat menüsüne "Ders Anlatıcı" kısayolu oluşturur (siyah pencere açmadan başlar).
$ErrorActionPreference = "Stop"
$kok = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = Join-Path $kok ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
$kabuk = New-Object -ComObject WScript.Shell
$hedefler = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) ""))
foreach ($klasor in $hedefler) {
  $k = $kabuk.CreateShortcut((Join-Path $klasor "Ders Anlatıcı.lnk"))
  $k.TargetPath = $pyw
  $k.Arguments = '"' + (Join-Path $kok "baslat.py") + '"'
  $k.WorkingDirectory = $kok
  $k.IconLocation = (Join-Path $kok "static\icon.ico")
  $k.Description = "Sesli, tahtalı kişisel ders hocası"
  $k.Save()
}
Write-Host "Masaüstüne 'Ders Anlatıcı' kısayolu eklendi."
