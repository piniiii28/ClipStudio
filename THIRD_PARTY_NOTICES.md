# Componentes adaptados

## OpenShorts

El tratamiento de metadatos y los parámetros de normalización de audio de
`clipstudio/entrega.py` se adaptaron de `ffmpeg_utils.py`.

Las reglas de zona de tolerancia, confirmación de desplazamientos y reinicio por
plano de `clipstudio/reframe_planos.py` se inspiran en `SmoothedCameraman` de `main.py`.
Este motor utiliza el detector YuNet de ClipStudio y PySceneDetect para los cortes.

Origen https://github.com/mutonby/openshorts/blob/main/ffmpeg_utils.py

Se conserva la licencia del repositorio de origen a continuación.

MIT License

Copyright (c) 2024 OpenShorts

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
