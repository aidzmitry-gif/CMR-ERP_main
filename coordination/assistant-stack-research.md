# Deep-research: тех-стек локального голосового AI-ассистента под AMD Strix Halo

> Источник: `/deep-research` 2026-06-15. 110 агентов, 27 источников, 125 фактов → 25 проверено
> адверсариально (3 голоса), 22 подтверждено, 3 опровергнуто. Под концепцию `Концепция_Личный_AI_Ассистент.md`.

## Железо
Ryzen AI Max+ (Strix Halo), iGPU Radeon 8060S = **gfx1151**, ~96–128 ГБ unified memory, NPU (XDNA2), NVMe, Windows 11.

## Главные выводы (подтверждено)

1. **Русская транскрипция — НЕ Whisper, а специализированные модели:**
   - **T-one** (71M, voicekit) — телефония: **8.63% WER vs 19.39% Whisper large-v3** на колл-центре (~2× точнее).
     **Работает на CPU** (4 ядра/8 ГБ), без GPU/CUDA → AMD-проблемы не касаются. github.com/voicekit-team/T-one
   - **GigaAM-v3** (Сбер, **MIT**) — встречи/общая речь, свободно коммерчески. huggingface.co/ai-sage/GigaAM-v3
   - Whisper/faster-whisper — фолбэк мультиязычности, на AMD через **Vulkan** (whisper.cpp), не ROCm.
   - ❌ ОПРОВЕРГНУТО (0-3): бенчмарк «GigaAM 6.7% vs Whisper 20.8% avg WER» — не цитировать.

2. **🔑 AMD-засада: Vulkan, НЕ ROCm.** На gfx1151 Vulkan/RADV быстрее ROCm на генерации (+25–32%) и
   стабильнее. ROCm 7.0.1 — баг порчи вывода (`GGGGGG…`), пропадает в CPU-режиме (ROCm issue #5499).
   Версионно-зависимо (7.1/7.2 могли починить) → перепроверять. **Вывод: GPU-инференс через Vulkan, ROCm — запасной.**

3. **Локальный LLM реально влезает:** 30B ~100 ток/с (Vulkan/llama.cpp), GPT-OSS 120B (~61 ГБ) помещается в
   96 ГБ. Запуск — LM Studio/llama.cpp на Vulkan. Но **основной мозг — подписка Claude Code**; локальный LLM =
   фолбэк/сверх-чувствительное.

4. **NPU (XDNA2) — НЕ применим:** Whisper/LLM на NPU есть (FastFlowLM/Lemonade), но **только Linux**; AMD
   Ryzen AI SDK не ставится на Strix Halo. У пользователя Windows → не рассчитываем.

5. **Запись 2 дорожек (Windows, платформо-независимо):** PyAudioWPatch (WASAPI loopback) + микрофон, либо
   SoundCard (`include_loopback=True`), либо OBS (до 6 дорожек). Раздельные дорожки → лёгкая диаризация.

6. **iPhone:** iOS 18.1+ — встроенная запись звонков (Телефон→Заметки). ⚠️ ОПРОВЕРГНУТО (1-2): что
   транскрипция «полностью on-device» и что авто-уведомление закрывает юр.вопрос.

7. **iFlytek (документирован SR302 Pro):** экспорт USB drag-and-drop, WAV + DOC, без проприетарного ПО,
   скриптуется (python-docx). SR101 — вероятно так же, проверить (возможно MTP).

8. **Шифрование at-rest:** BitLocker или VeraCrypt (полнодисковое, pre-boot auth).

## Диаризация
pyannote.audio / WhisperX — на AMD через CPU/Vulkan, не ROCm. ⚠️ Рабочий AMD-конвейер напрямую НЕ
подтверждён — проверить. Раздельная запись дорожек снижает зависимость от тяжёлой диаризации.

## Открытые вопросы (перенесены в §10 концепции)
- ROCm vs Vulkan на Windows для gfx1151 (баг жив на 7.1/7.2?).
- Реальная точность T-one/GigaAM на своём аудио + работает ли диаризация на AMD.
- SR101: mass-storage или MTP? авто-watcher надёжен?
- Юр. требования РБ/РФ к записи сотрудников/клиентов.

## Ключевые источники
- T-one: github.com/voicekit-team/T-one
- GigaAM: huggingface.co/ai-sage/GigaAM-v3 · github.com/salute-developers/GigaAM
- ROCm баг: github.com/ROCm/ROCm/issues/5499 · phoronix.com/review/amd-rocm-7-strix-halo
- Strix Halo LLM: github.com/hogeheer499-commits/strix-halo-guide · hardware-corner.net/strix-halo-llm-optimization
- Запись: github.com/s0d3s/PyAudioWPatch · soundcard.readthedocs.io · obsproject.com/kb/multiple-audio-track-recording-guide
- iPhone/iFlytek: macrumors.com/how-to/ios-record-your-phone-calls · iflytek SR302 Pro manual (PDF)
- Шифрование: veracrypt.io/en/System%20Encryption.html
