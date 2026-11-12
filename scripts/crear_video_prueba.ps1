# Genera un video de prueba propio (voz sintetica de Windows + patron de video) para validar ClipStudio.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\crear_video_prueba.ps1 [-Salida ruta.mp4]
param([string]$Salida = "")

$ErrorActionPreference = "Stop"
$datos = if ($env:CLIPSTUDIO_DATA_DIR) { $env:CLIPSTUDIO_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "ClipStudio" }
$ffmpeg = Join-Path $datos "bin\ffmpeg.exe"
if (-not (Test-Path $ffmpeg)) { $ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source }
$carpeta = Join-Path $datos "pruebas"
New-Item -ItemType Directory -Force $carpeta | Out-Null
if (-not $Salida) { $Salida = Join-Path $carpeta "video_prueba.mp4" }
$wav = Join-Path $carpeta "voz_prueba.wav"

$pausa = '<break time="1500ms"/>'
$parrafos = @(
    "Bienvenidos a este video de prueba. Hoy vamos a hablar de como organizar mejor una semana de trabajo.",
    "Sabias que la mayoria de las personas pierde casi 2 horas al dia cambiando de una tarea a otra? Ese cambio constante tiene un costo real. Cada vez que saltas de un correo a un informe, tu atencion tarda varios minutos en volver. La solucion mas simple es agrupar tareas parecidas en bloques de tiempo.",
    "El primer consejo es planear la semana el domingo por la tarde. Escribe las 3 cosas mas importantes que quieres terminar. No 10, solo 3. Cuando todo es prioridad, nada lo es.",
    "El segundo consejo es proteger las mananas. Durante las primeras horas tu energia es mas alta. Usa ese tiempo para el trabajo dificil y deja las reuniones para despues del almuerzo.",
    "Y que pasa con las interrupciones? Aqui va una regla practica. Si algo toma menos de 2 minutos, hazlo de inmediato. Si toma mas, anotalo y sigue con lo que estabas haciendo.",
    "Para terminar, recuerda descansar. Una pausa corta cada 50 minutos mejora la concentracion mas que trabajar sin parar. Gracias por ver este video y hasta la proxima."
)
$texto = $parrafos -join " $pausa "

Add-Type -AssemblyName System.Speech
$voz = New-Object System.Speech.Synthesis.SpeechSynthesizer
$es = $voz.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like "es-*" } | Select-Object -First 1
if ($es) {
    $voz.SelectVoice($es.VoiceInfo.Name)
    $idioma = $es.VoiceInfo.Culture.Name
} else {
    $idioma = $voz.Voice.Culture.Name
    Write-Host "Aviso: no hay voz en espanol instalada; se usa $idioma"
}
$voz.SetOutputToWaveFile($wav)
$voz.SpeakSsml("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='$idioma'>$texto</speak>")
$voz.Dispose()

# Video 1280x720: patron en movimiento con contador de tiempo, mas la voz generada.
& $ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=1280x720:rate=30" -i $wav -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 128k -shortest $Salida
if ($LASTEXITCODE -ne 0) { throw "ffmpeg fallo al crear el video de prueba" }
Remove-Item $wav -Force
Write-Host "Video de prueba creado: $Salida"
