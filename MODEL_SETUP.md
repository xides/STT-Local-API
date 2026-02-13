Instrucciones para preparar el modelo para faster-whisper (ctranslate2)

1) Requisitos
- Python 3.10+
- pip
- ctranslate2 and transformers

2) Convertir el modelo openai/whisper-small a formato ctranslate2 (local)

pip install ctranslate2 transformers
python -c "from ctranslate2.converters import convert_model; convert_model('openai/whisper-small', 'ctranslate2_model', 'whisper', quantization=None)"

3) Mover el resultado al cache de Hugging Face (ejemplo)

mkdir -p ~/.cache/huggingface/hub/models--openai--whisper-small/snapshots/converted
mv ctranslate2_model/* ~/.cache/huggingface/hub/models--openai--whisper-small/snapshots/converted/

Asegúrate de que en la carpeta exista un archivo model.bin y los ficheros necesarios para ctranslate2.

4) Alternativa: usar un modelo ya convertido y especificar su ruta en la variable de entorno MODEL_NAME

export MODEL_NAME="/ruta/al/modelo/ctranslate2"

5) Notas
- faster-whisper usa ctranslate2 para cargar modelos localmente. Si model.bin no existe, la carga fallará.
- No es necesario instalar PyTorch para ejecutar este servicio en CPU.
- En macOS/ARM puede ser necesario instalar ctranslate2 con soporte apropiado.
